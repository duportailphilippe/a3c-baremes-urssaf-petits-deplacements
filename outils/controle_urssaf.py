"""A3C - Veille des plafonds URSSAF de petits déplacements.

Ce programme ne publie ni ne modifie jamais le barème validé.
Statuts distincts: conforme, source inaccessible, évolution à valider,
publication illisible, référentiel local invalide.
Fonctionne avec la bibliothèque standard Python 3.12.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser
from http.client import RemoteDisconnected
from pathlib import Path
import json
import os
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REFERENTIEL = ROOT / "donnees/petits-deplacements-urssaf.json"
PROPOSITION = ROOT / "donnees/proposition-changement.json"
RESULTAT = ROOT / "donnees/resultat-controle.json"
SOURCES = (
    "https://www.urssaf.fr/accueil/outils-documentation/taux-baremes/frais-professionnels.html",
    "https://www.urssaf.fr/accueil/employeur/beneficier-exonerations/frais-professionnels.html",
)
ENTETE = re.compile(r"Indemnit[eé]\s+de\s+petit\s+d[eé]placement\s*[-–—]\s*Montants\s+pour\s+(20\d{2})", re.I)
LIGNE = re.compile(r"(\d{1,3})\s*km\s*et\s*(\d{1,3})\s*km\s*\|?\s*(\d{1,3}[,.]\d{2})\s*€", re.I)
MAJORATION = re.compile(r"v[eé]hicule\s+[eé]lectrique.{0,220}?20\s*%", re.I | re.S)


class TexteHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.morceaux = []
        self.invisibles = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.invisibles += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.invisibles:
            self.invisibles -= 1

    def handle_data(self, data):
        if not self.invisibles:
            self.morceaux.append(data)


def normaliser_tranches(tranches):
    if len(tranches) != 20:
        raise ValueError(f"20 tranches attendues, {len(tranches)} trouvées")
    resultat = []
    for i, t in enumerate(tranches):
        debut_attendu = 5 if i == 0 else i * 10
        fin_attendue = (i + 1) * 10
        try:
            debut = int(t["de_km"])
            fin = int(t["a_km"])
            montant = Decimal(str(t["euros"]).replace(",", "."))
        except (ValueError, KeyError, TypeError, InvalidOperation) as err:
            raise ValueError(f"Tranche {i + 1} illisible : {err}") from err
        if (debut, fin) != (debut_attendu, fin_attendue):
            raise ValueError(f"Bornes incohérentes à la tranche {i + 1} : {debut}-{fin} km")
        if not Decimal("0") < montant < Decimal("150"):
            raise ValueError(f"Montant incohérent à la tranche {i + 1}")
        if resultat and montant <= resultat[-1]["euros"]:
            raise ValueError(f"Montants non croissants à la tranche {i + 1}")
        resultat.append({"de_km": debut, "a_km": fin, "euros": montant})
    return resultat


def extraire(html_source):
    lecteur = TexteHTML()
    lecteur.feed(html_source)
    texte = re.sub(r"\s+", " ", unescape(" ".join(lecteur.morceaux)))
    entetes = list(ENTETE.finditer(texte))
    if not entetes:
        raise ValueError("Titre du tableau des petits déplacements introuvable")
    annee = max(int(m.group(1)) for m in entetes)
    tableaux = []
    for i, debut in enumerate(entetes):
        if int(debut.group(1)) != annee:
            continue
        fin = entetes[i + 1].start() if i + 1 < len(entetes) else len(texte)
        partie = texte[debut.end():fin].split("Grand déplacement")[0]
        lignes = [{"de_km": int(a), "a_km": int(b), "euros": v.replace(",", ".")}
                  for a, b, v in LIGNE.findall(partie)]
        if lignes:
            tableaux.append(normaliser_tranches(lignes))
    if not tableaux:
        raise ValueError("Aucune ligne du barème n'a pu être extraite")
    if any(t != tableaux[0] for t in tableaux[1:]):
        raise ValueError("Les tableaux publiés pour une même année divergent")
    # Le texte détaillé peut être après le dernier tableau ; ne pas tester
    # uniquement les premières lignes pour éviter un faux négatif.
    apres_entete = texte[entetes[0].start():]
    if not MAJORATION.search(apres_entete):
        raise ValueError("La majoration de 20 % pour véhicule électrique n'a pas été identifiée")
    return annee, tableaux[0]


def telecharger(url, tentatives=2):
    erreurs = []
    for tentative in range(tentatives):
        try:
            requete = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
                "Cache-Control": "no-cache",
            })
            with urllib.request.urlopen(requete, timeout=15) as reponse:
                brut = reponse.read(3_000_000)
                if len(brut) >= 3_000_000:
                    raise ValueError("Réponse trop volumineuse")
                charset = reponse.headers.get_content_charset() or "utf-8"
                return brut.decode(charset, errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                ConnectionError, RemoteDisconnected, socket.timeout, ssl.SSLError, ValueError) as exc:
            erreurs.append(f"tentative {tentative + 1}: {type(exc).__name__}: {exc}")
            if tentative + 1 < tentatives:
                time.sleep(2)
    raise RuntimeError(" ; ".join(erreurs))


def sauvegarder_resultat(statut, message, *, source=None, annee=None, detail_sources=None):
    donnees = {
        "date_controle_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "statut": statut,
        "message": message,
        "source": source,
        "annee": annee,
        "sources_consultees": list(SOURCES),
        "details": detail_sources or [],
        "referentiel_modifie": False,
    }
    RESULTAT.parent.mkdir(parents=True, exist_ok=True)
    RESULTAT.write_text(json.dumps(donnees, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"STATUT : {statut} — {message}")
    resume = os.environ.get("GITHUB_STEP_SUMMARY")
    if resume:
        with open(resume, "a", encoding="utf-8") as f:
            f.write(f"## Veille URSSAF — {statut}\n\n{message}\n\n")
            f.write("Aucun montant validé n'a été modifié automatiquement.\n")
    return 0 if statut == "CONFORME" else 1


def executer():
    try:
        historique = json.loads(REFERENTIEL.read_text(encoding="utf-8"))["historique"]
        if not isinstance(historique, list):
            raise ValueError("historique doit être une liste")
        # Validation complète du JSON existant pour garantir les rapprochements.
        for fiche in historique:
            normaliser_tranches(fiche["tranches"])
            if int(fiche["majoration_electrique_pct"]) != 20:
                raise ValueError("Majoration locale non conforme")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return sauvegarder_resultat("REFERENTIEL_INVALIDE", f"Référentiel A3C non exploitable : {exc}")

    echecs_connexion = []
    echecs_extraction = []
    extractions = []
    for url in SOURCES:
        try:
            page = telecharger(url)
        except Exception as exc:
            echecs_connexion.append(f"{url} : {exc}")
            continue
        try:
            annee, tranches = extraire(page)
        except Exception as exc:
            echecs_extraction.append(f"{url} : {exc}")
            continue
        extractions.append((url, annee, tranches))

    if not extractions:
        if echecs_extraction:
            return sauvegarder_resultat("PUBLICATION_ILLISIBLE",
                "Page(s) URSSAF reçue(s), mais le barème n'a pas pu être extrait. Contrôle humain nécessaire.",
                detail_sources=echecs_connexion + echecs_extraction)
        return sauvegarder_resultat("SOURCE_INACCESSIBLE",
            "Les deux pages officielles URSSAF n'ont pas répondu. Aucune modification du barème ne peut être déduite.",
            detail_sources=echecs_connexion)

    # Si plusieurs pages ont pu être lues, la plus récente fait référence,
    # mais deux versions différentes de la même année sont suspectes.
    annee = max(x[1] for x in extractions)
    valides = [(url, tranches) for url, an, tranches in extractions if an == annee]
    if any(t != valides[0][1] for _, t in valides[1:]):
        return sauvegarder_resultat("PUBLICATION_ILLISIBLE",
            f"Les pages officielles ne présentent pas les mêmes montants pour {annee}.",
            annee=annee, detail_sources=[x[0] for x in extractions])
    source, tranches = valides[0]
    connu = next((r for r in historique if int(r["annee"]) == annee), None)
    compare = normaliser_tranches(connu["tranches"]) if connu else None
    if connu is None or compare != tranches:
        proposition = {
            "annee": annee,
            "source": source,
            "tranches": [{**t, "euros": float(t["euros"])} for t in tranches],
            "majoration_electrique_pct": 20,
            "date_detection_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "statut": "PROPOSITION_NON_VALIDEE",
        }
        PROPOSITION.write_text(json.dumps(proposition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raison = "Nouvelle année" if connu is None else "Montants différents"
        return sauvegarder_resultat("EVOLUTION_A_VALIDER",
            f"{raison} sur la publication officielle ({annee}). Proposition enregistrée pour validation humaine.",
            source=source, annee=annee)
    return sauvegarder_resultat("CONFORME", f"Barème {annee} conforme : 20 tranches identiques au référentiel A3C.",
        source=source, annee=annee,
        detail_sources=echecs_connexion + echecs_extraction)


if __name__ == "__main__":
    sys.exit(executer())
