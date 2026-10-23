# What the founder answered at the review (each line is one decision, recorded in decisions.json).
K="$1"; B="$2"
python3 "$K" master "$B" brand
python3 "$K" ownership "$B" ev-$(python3 -c "import hashlib;print(hashlib.sha1(b'web_image|https://archive.example/2019/marrowbay-label-green.png').hexdigest()[:8])") official --reason "yes, that was our label until 2021"
python3 "$K" ownership "$B" ev-$(python3 -c "import hashlib;print(hashlib.sha1(b'web_image|https://social.example/marrowbayferments/p/123').hexdigest()[:8])") uncertain --reason "not ours, a reseller's account"
python3 "$K" confirm "$B" imagery.style
python3 "$K" reject "$B" voice.register --reason "not dry. Warm and plain, yes; dry, no."
