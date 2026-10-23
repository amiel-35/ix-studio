<p align="center">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-8f8a7c"></a>
  <img alt="Claude Code" src="https://img.shields.io/badge/Claude%20Code-plugin-D97757">
  <img alt="Status" src="https://img.shields.io/badge/status-experimental-e07a3f">
</p>

<p align="center"><a href="README.md"><b>English</b></a></p>

# studio

Un plugin Claude Code qui fait **une pub en une session** : une affiche ou un post pour une marque, de dix lignes
sur la marque à une pièce que tu gardes ou que tu renvoies. Chaque étape est une page qu'on regarde et où l'on tranche.

```
marque (10 lignes) → brief → divergence → pièce → contrôle → tu tranches
```

<p align="center"><img src="examples/marrowbay/poster/piece.png" width="320" alt="Une affiche pour une marque fictive de kombucha"></p>

## Installer

```bash
claude plugin marketplace add amiel-35/ix-studio
claude plugin install studio@ix-studio
```

Prérequis : Claude Code et Python 3.10+. En option : Chrome ou Chromium (pour `piece.png`), un générateur d'images
(plus bas).

## Utiliser

Dans Claude Code, dans n'importe quel dossier :

> /studio une affiche pour Marrowbay Ferments, un petit fabricant de kombucha : donner envie aux citadins d'y goûter

Claude écrit avec toi les lignes de marque et le brief, ouvre une page par étape et te dit la seule question que
chaque page pose. Tout ce qui concerne la pièce vit dans `poster/` :

| Étape | Tu donnes ou Claude écrit | Page | Ta décision |
|---|---|---|---|
| 1 Marque | `brand.md` : nom, couleurs, typos, logo, ton, interdits (tes mots, un skill de design system ou un dossier de marque) | `1-brand.html` | est-ce la marque ? |
| 2 Brief | `brief.md` : objectif, cible, message, format | `2-brief.html` | est-ce le travail ? |
| 3 Divergence | `variants/*.json` : variantes en aveugle, une par mandat, chacune avec le défaut qu'elle a écarté | `3-divergence.html` | en choisir une |
| 4 Pièce | l'image (générée, ou la tienne), l'accroche posée en HTML | `4-piece.html`, `piece.png` | |
| 5 Contrôle | palette, typo, contraste, mots interdits, plus les notes d'un juge qui ne bloquent jamais | `5-check.html` | garder, ou refaire |

Pour une pub, l'unité est le couple **accroche + image** : l'accroche d'abord, l'image lui répond. Le modèle d'image
n'écrit jamais de texte. La divergence suit la méthode de
[design-divergent](https://github.com/amiel-35/ix-design-divergent) (des mandats qui regardent chacun ailleurs, des
variantes en aveugle, l'attracteur, tu choisis).

## Les deux fichiers qu'on peut écrire à la main

`brand.md`, une ligne `clé: valeur` par entrée : `name`, `background`, `text` (obligatoires) ; `accent`,
`extra colours` (séparées par des virgules), `headline colour` (hex) ; `headline font`, `body font` ; `logo` (un
fichier, ou `placeholder`), `logo position` (`bottom-right`, `bottom-left`, `top-right`, `top-left`, `bottom-center` : logo centré, slogan
dessous) ; `headline case` (`as written` ou `upper`) ; `slogan` (mots exacts, posé près du logo) ; `voice` ; `never` (mots ou caractères exacts, séparés par `;`) ; `never show` (ce que
l'image ne doit pas montrer) ; `notes`. Une valeur suivie de `(à confirmer)` est utilisée, et le contrôle signale que
la pièce s'appuie dessus.

`brief.md` : `objective`, `audience`, `message` (obligatoires) ; `format` ; `fixed` ; `cta` ; `language`.

Formats : `post-4x5` (1080×1350, par défaut), `post-1x1` (1080×1080), `story` (1080×1920), `poster-a3` (1240×1754),
`poster-3x2` (1800×1200), `linkedin` (1200×627), ou une taille libre comme `1600x900` (largeur x hauteur, 200 à 4000 px de côté).

## Images

| Moteur | Comment | Quand |
|---|---|---|
| ta clé | `export OPENAI_API_KEY=...` (modèle : `STUDIO_IMAGE_MODEL`, par défaut `gpt-image-1`) | partout |
| ton forfait | le [CLI Codex](https://github.com/openai/codex), installé et connecté | sur ta machine ; vérifie que les conditions de ton forfait couvrent cet usage |
| ton fichier | dépose `image.png` dans le dossier de la pièce | toujours |
| aucun | rien à installer | la pièce est composée sur un fond de marque uni, et la page le dit |

## Sans Claude

Chaque étape est une commande ; écris son fichier d'entrée à la main et lance-la seule, ou rejoue tout l'exemple :

```bash
python3 scripts/studio status poster        # où tu en es, et la commande suivante
sh examples/marrowbay/poster/build.sh       # l'exemple fictif, de bout en bout, sans générateur
python3 -m unittest discover -s tests       # les tests, dont le flux de bout en bout
```

## Aller plus loin

Le **dossier de marque** riche (provenance de chaque valeur, inférence depuis un site, conflits, versions) est
toujours là, et facultatif : skill `brand-dossier`, puis `python3 scripts/studio brand poster --from-dossier brand`
pour démarrer une pièce depuis lui (valeurs confirmées seulement ; `--include-unconfirmed` prend aussi les
autres, marquées à confirmer). Voir [le dossier de marque](docs/fr/dossier-de-marque.md) et
[l'architecture](docs/fr/architecture.md).

Expérimental. MIT, voir [LICENSE](LICENSE) et [THIRD_PARTY.md](THIRD_PARTY.md). Marrowbay Ferments est fictive.
