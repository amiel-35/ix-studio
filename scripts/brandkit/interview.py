"""The free-text adapter's interview: the two batches of brand-intake, plus a third for the fields this dossier
adds, but only the questions whose answer is still missing after the skill and the inference (spec section 6).
An inferred value waiting for confirmation is not asked again: it goes to the review.
"""

from fuse import iter_values

QUESTIONS = [
    (1, ("identity.name", "identity.one_liner"), {
        "en": "What is the brand called, and what does it do, in one line?",
        "fr": "Comment s'appelle la marque, et que fait-elle, en une ligne ?"}),
    (1, ("audience.who", "audience.situation"), {
        "en": "Who is it for? One sentence on the person watching, and the situation they are in.",
        "fr": "C'est pour qui ? Une phrase sur la personne qui regarde, et la situation où elle est."}),
    (1, ("identity.offer", "identity.links"), {
        "en": "What do you sell or promote? The offer or product, with its real link.",
        "fr": "Qu'est-ce que tu vends ou mets en avant ? L'offre ou le produit, avec son vrai lien."}),
    (1, ("voice.traits",), {
        "en": "What should people feel in the first second? Up to three: calm, premium, playful, urgent, technical, warm, bold.",
        "fr": "Que doit-on ressentir dans la première seconde ? Trois au plus : calme, premium, joueur, urgent, technique, chaleureux, audacieux."}),
    (2, ("colours", "typography", "logo"), {
        "en": "Your colours as hex codes, your font names (with their files and licence if you have them), your logo files (SVG if possible).",
        "fr": "Tes couleurs en hexadécimal, tes polices (avec leurs fichiers et leur licence si tu les as), tes fichiers de logo (SVG si possible)."}),
    (2, ("references",), {
        "en": "Three to five references you like (links or files), and for each, what you take from it.",
        "fr": "Trois à cinq références que tu aimes (liens ou fichiers), et pour chacune, ce que tu en prends."}),
    (2, ("motion.never", "imagery.dont"), {
        "en": "One thing the brand must never do on screen.",
        "fr": "Une chose que la marque ne doit jamais faire à l'écran."}),
    (3, ("promise.tagline", "promise.signature_line", "promise.key_messages"), {
        "en": "Your tagline, signature line and key messages, word for word (they will not be rephrased).",
        "fr": "Ton slogan, ta signature et tes messages clés, mot pour mot (ils ne seront pas reformulés)."}),
    (3, ("voice.register", "voice.address"), {
        "en": "How do you address people (tu, vous, you; first names?), and how formal is the tone?",
        "fr": "Comment tu t'adresses aux gens (tu, vous, prénom ?), et le ton est-il formel ou pas ?"}),
    (3, ("motion.tempo", "motion.entrances", "motion.exits", "motion.easing"), {
        "en": "How should things move: fast or slow, how they come in and leave? Skip it if you do not know: it stays ASK ME.",
        "fr": "Comment les choses bougent : vite ou lentement, comment elles entrent et sortent ? Passe si tu ne sais pas : ça reste ASK ME."}),
]


def missing_questions(doc, lang="en"):
    status = {}
    for path, v in iter_values(doc):
        root = path.split("[")[0]
        status.setdefault(root, []).append(v.get("status"))
        status.setdefault(path, []).append(v.get("status"))
    out = []
    for batch, fields, q in QUESTIONS:
        gaps = []
        for f in fields:
            sts = status.get(f, [])
            if not sts or any(s in ("ask", "to_create") for s in sts):
                if f in ("colours", "typography", "logo") and sts and all(s in ("confirmed", "to_confirm") for s in sts):
                    continue
                gaps.append(f)
        if gaps:
            out.append({"batch": batch, "question": q.get(lang, q["en"]), "fields": gaps})
    return out
