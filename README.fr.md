<p align="center">
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-8f8a7c"></a>
  <img alt="Claude Code" src="https://img.shields.io/badge/Claude%20Code-plugin-D97757">
  <img alt="Part" src="https://img.shields.io/badge/part%201-brand%20dossier-3d9a8b">
  <img alt="Status" src="https://img.shields.io/badge/status-experimental-e07a3f">
</p>

<p align="center">
  <a href="#démarrage-rapide"><b>Démarrage rapide</b></a> ·
  <a href="#à-quoi-ça-ressemble"><b>À quoi ça ressemble</b></a> ·
  <a href="#documentation"><b>Documentation</b></a> ·
  <a href="README.md"><b>English</b></a>
</p>

---

# studio

Demande à un modèle « un visuel pour cette marque » et il lui donnera une palette, une typo et un ton. Les siens.

**studio** est un plugin Claude Code pour le travail créatif sur n'importe quelle marque, même une dont tu ne sais
rien. Il part de là où tout brief créatif devrait partir : écrire ce qu'on sait vraiment de la marque, d'où vient
chaque élément, et ce que personne n'a encore dit. Cette première version, c'est cette partie, le **dossier de
marque**. Le reste du studio (brief, divergence, exécution, contrôles) le lit.

## Ce qu'il fait

- **Rassemble** ce que dit un skill de design system, ce que montrent le site, les fichiers et les vidéos de la
  marque, ce qui ressort d'une recherche d'images sur le web, et ce que tu écris.
- **Garde la provenance de chaque valeur** : saisie, skill, déduite, créée ; la page et la date, le fichier, la
  version du skill ; pour tout ce qui est déduit, ses preuves et un niveau de confiance.
- **Ne devine jamais.** Une valeur manquante, c'est « À DEMANDER », dans le dossier comme dans les exports. Pas de
  palette par défaut, pas de police « provisoire », pas de baseline écrite à la place de la marque.
- **Fusionne avec une priorité fixe** (skill, puis saisi, puis déduit) et **garde les conflits** là où tu peux les
  voir.
- **Nomme plusieurs looks au lieu de les moyenner** (l'identité actuelle, une ancienne, une campagne) et demande
  lequel est le look maître.
- **Montre une seule revue**, groupée par élément, y compris les images trouvées sur le web qu'il croit être celles
  de la marque, pour que tu les confirmes ou les corriges.
- **Exporte** `brand.md` et `MOTION.md` au format de
  [brand-intake](https://github.com/charlie947/motion-graphics-skills), pour que les skills qui les lisent
  fonctionnent tels quels.

## À quoi ça ressemble

Une marque fictive, Marrowbay Ferments, construite à partir d'un skill de design system, de son site, d'une
recherche d'images sur le web et d'un court entretien ([tout l'exemple](examples/marrowbay)). Un extrait de la
revue :

```
## Colours
- **Conflict** `colours` (look brand): kept hex: #C8553D, role: accent, name: Brick [skill: marrowbay-ds@1.2.0] over hex: #E07A2F, role: accent, share: 0.04 [inferred: https://marrowbay.example (2026-10-23)]
- Inferred, to confirm `colours[old-identity:background]`: hex #2F5D3A · role background (confidence low; proof ev-d5fff827)

## Looks
**Several looks were found. Which one is the master look? Nothing is averaged meanwhile.**
- `summer-2026`: Summer 2026 campaign (campaign), proof ev-16125880
- `old-identity`: Identity before 2021 (old_identity), proof ev-d5fff827
- `brand`: Brand identity (brand)

## Visuals and pages: are they the brand's?
- `ev-9aee9706` web_image https://pins.example/kombucha-moodboard-44: **uncertain** · moodboard with a Marrowbay bottle among others
- `ev-b0cba8e4` web_image https://social.example/marrowbayferments/p/123: **official** · post on the brand's own account: bottles on a market stall
```

Le fondateur a répondu que le post sur les réseaux était celui d'un revendeur, pas le sien : ce qui reposait
uniquement dessus est sorti du dossier. Et voici ce que reçoit un module en aval quand il demande un champ que
personne n'a rempli :

```bash
$ python3 scripts/brandkit get examples/marrowbay/brand audience.situation
{"path": "audience.situation", "status": "ask", "missing": true,
 "say": "no value: ask the user or stop. Never fill it in."}
```

## Démarrage rapide

```bash
claude plugin marketplace add amiel-35/ix-studio
claude plugin install studio@ix-studio
```

Ou en simple clone, si tu veux le lire et le modifier sur place : clone le dépôt où tu veux et pointe Claude Code
dessus avec `claude --plugin-dir <clone>`.

Ensuite, dans Claude Code : « monte le dossier de marque pour <marque> », avec ce que tu as (un site, un dossier, le
nom d'un skill de design system). Ou appelle `/studio` et il t'orientera.

Prérequis : Python 3.10+ ; pour l'inférence depuis un site, Node 22+ et un Chrome installé (ou Chromium, Edge,
Brave) ; pour les vidéos et les couleurs des images, ffmpeg.

Depuis un clone, sans installer : `python3 scripts/brandkit --help`, et `sh examples/marrowbay/build.sh` pour
reconstruire l'exemple.

## Documentation

- [Le dossier de marque](docs/fr/dossier-de-marque.md) : objectif, règles, adaptateurs, modèle de données, cas
  limites, critères d'acceptation.
- [Architecture](docs/fr/architecture.md) : les modules du studio et les contrats entre eux.
- [Le skill](skills/brand-dossier/SKILL.md) et ses références : format des sources, chaque adaptateur, la recherche
  d'images sur le web.
- [Travaux tiers](THIRD_PARTY.md) : ce qui vient de huashu-motion et de brand-intake, sous leurs licences.

## Statut

Expérimental. Partie 1 sur 5. La divergence est le plugin séparé
[design-divergent](https://github.com/amiel-35/ix-design-divergent) ; le traitement, l'exécution, les contrôles et
la mémoire sont prévus.

## Licence

MIT. Voir [LICENSE](LICENSE) et [THIRD_PARTY.md](THIRD_PARTY.md).
