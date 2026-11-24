# Changelog

Sve značajne promjene idu ovdje. Format: [Keep a Changelog](https://keepachangelog.com/),
verzije po [SemVer](https://semver.org/).

## [0.1.2] - 2026-11-24

### Fixed

- `manifest.json` ključevi su poredani kako hassfest traži (`domain`, `name`,
  pa abecedno), pa validacija prolazi. Build skripta sada odbija napraviti zip
  s pogrešnim poretkom.

## [0.1.1] - 2026-11-24

### Fixed

- **Layout release zipa.** HACS raspakirava release asset direktno u
  `custom_components/<domena>`, pa zip sada sadrži `manifest.json` u korijenu
  umjesto ugniježđene `custom_components/` mape. 0.1.0 instaliran preko HACS-a
  završio je kao `custom_components/bonbon/custom_components/bonbon/manifest.json`,
  što Home Assistant prijavljuje kao integraciju bez manifesta.
- Verzija za cache-busting kartice čita se iz `manifest.json` umjesto iz druge
  hardkodirane konstante.

## [0.1.0] - 2026-11-24

### Added

- Prva verzija integracije `bonbon` za Home Assistant 2026.11+.
- Prijava preko sesije iz preglednika ("Copy as cURL"), bez lozinke i bez
  automatizacije Google prijave.
- Perzistentni cookie jar koji preživi restart Home Assistenta.
- Dvostupanjsko tiho obnavljanje sesije: prvo preko otvorene portala stranice,
  zatim SSO handshake s `prompt=none`; reauth flow tek kad oboje padne.
- Polling svaka 3 sata, podesivo 1–24 h.
- Više brojeva po računu, svaki kao zaseban uređaj; podaci se dohvaćaju po broju
  (`/profile/status` i `/package/list-all2` s `{"msisdn": ...}`).
- Senzori: broj, stanje računa (+ `spending` i `portal_message`), valjanost
  (+ `days_left`), aktivni paketi (s atributima), preostale količine za
  podatke/minute/SMS.
- Graciozno ponašanje kad portal za neki broj vrati `status.success: 0`
  (istekao / neregistriran broj): broj ostaje vidljiv, kartica pokaže poruku
  portala umjesto praznih polja.
- Kartica `custom:bonbon-card` s više brojeva, animiranim stanjem, ringom
  valjanosti, progress barovima paketa i porukom portala; automatski se
  registrira kao frontend resurs.
- HACS metadata (`zip_release`), hassfest/HACS/ruff provjere, HA test harness
  testovi i release workflow na tag.
