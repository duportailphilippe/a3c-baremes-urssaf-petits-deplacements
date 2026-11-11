"""Veille du barème URSSAF des petits déplacements — référentiel A3C.

Lecture seule des pages officielles. N'actualise jamais le barème validé :
toute nouveauté/anomalie nécessite une vérification humaine.
"""
import datetime
import html
import json
import pathlib
import re
import sys
import urllib.request
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
FICHIER = ROOT / "donnees" / "petits-deplacements-urssaf.json"
PROPOSITION = ROOT / "donnees" / "proposition-changement.json"
SOURCES = (
    "https://www.urssaf.fr/accueil/outils-documentation/taux-baremes/frais-professionnels.html",
    "https://www.urssaf.fr/accueil/employeur/beneficier-exonerations/frais-professionnels.html",
)
ENTETE = re.compile(
    r"Indemnité\s+de\s+petit\s+déplacement\s*[-–—]\s*Montants\s+pour\s+(20\d{2})",
    flags=re.IGNORECASE,
)
LIGNE = re.compile(
    r"(\d{1,3})\s*km\s*et\s*(\d{1,3})\s*km\s*\|?\s*(\d{1,3}[,.]\d{2})\s*€",
    flags=re.IGNORECASE,
)


class LecteurHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.morceaux = []

    def handle_data(self, data):
        self.morceaux.append(data)


def extraire(page):
    lecteur = LecteurHTML()
    lecteur.feed(page)
    texte = re.sub(r"\s+", " ", html.unescape(" ".join(lecteur.morceaux)))
    entetes = list(ENTETE.finditer(texte))
    if not entetes:
        raise ValueError("La section 'Indemnité de petit déplacement' est introuvable")
    annee = max(int(x.group(1)) for x in entetes)
    morceaux = []
    for i, debut in enumerate(entetes):
        if int(debut.group(1)) != annee:
            continue
        fin = entetes[i + 1].start() if i + 1 < len(entetes) else len(texte)
        segment = texte[debut.end():fin].split("Grand déplacement")[0]
        lignes = [
            {"de_km": int(a), "a_km": int(b), "euros": float(v.replace(",", "."))}
            for a, b, v in LIGNE.findall(segment)
        ]
        if lignes:
            morceaux.append((lignes, segment))
    if not morceaux:
        raise ValueError("Aucune tranche kilométrique extractible")
    tranches, portion = morceaux[0]
    if len(tranches) != 20:
        raise ValueError(f"20 tranches attendues, {len(tranches)} trouvées")
    for i, tranche in enumerate(tranches):
        borne_inf = 5 if i == 0 else 10 * i
        borne_sup = 10 * (i + 1)
        if (tranche["de_km"], tranche["a_km"]) != (borne_inf, borne_sup):
            raise ValueError(f"Tranche {i + 1} incohérente")
        if not 0 < tranche["euros"] < 150:
            raise ValueError(f"Montant anormal, tranche {i + 1}")
        if i and tranche["euros"] <= tranches[i - 1]["euros"]:
            raise ValueError(f"Montants non croissants, tranche {i + 1}")
    for autres, _ in morceaux[1:]:
        if autres != tranches:
            raise ValueError("Deux tableaux URSSAF pour la même année divergent")
    # Ne pas présumer la majoration constante d'une année à l'autre.
    fragment = texte[entetes[0].start():].lower()
    if not re.search(r"véhicule\s+électrique.{0,160}?20\s*%", fragment):
        raise ValueError("Majoration électrique de 20 % non retrouvée dans la publication")
    return annee, tranches


def recuperer():
    erreurs = []
    for url in SOURCES:
        try:
            requete = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; A3C-ControleBaremes/1.1)",
                    "Accept-Language": "fr-FR,fr;q=0.9",
                },
            )
            with urllib.request.urlopen(requete, timeout=30) as reponse:
                contenu = reponse.read().decode("utf-8-sig")
            annee, tranches = extraire(contenu)
            return url, annee, tranches
        except Exception as exc:
            erreurs.append(f"{url} : {exc}")
    raise RuntimeError("Échec de lecture des deux pages URSSAF : " + " ; ".join(erreurs))


def executer():
    source, annee, tranches = recuperer()
    if annee < datetime.date.today().year - 1:
        raise ValueError(f"Année publiée trop ancienne : {annee}")
    enregistrements = json.loads(FICHIER.read_text(encoding="utf-8"))["historique"]
    fiche = {
        "annee": annee,
        "source": source,
        "tranches": tranches,
        "majoration_electrique_pct": 20,
    }
    connu = next((r for r in enregistrements if r["annee"] == annee), None)
    if connu is None or any(connu.get(k) != fiche[k] for k in ("tranches", "majoration_electrique_pct")):
        PROPOSITION.write_text(json.dumps(fiche, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raison = "nouvelle année" if connu is None else "modification de barème"
        raise ValueError(f"ALERTE : {raison} ({annee}) — validation humaine requise")
    print(f"OK : barème URSSAF {annee} conforme, 20 tranches, source : {source}")


if __name__ == "__main__":
    try:
        executer()
    except Exception as erreur:
        print(f"CONTRÔLE À EFFECTUER : {erreur}", file=sys.stderr)
        sys.exit(1)
