# Kadar

*[English](README.md)*

Alat za screenshot na Linuxu u stilu Flameshot-a, napravljen za Wayland i
frakcionalno skaliranje (125 %, 150 %, 160 %, 175 %…). Python + GTK 4.

Kompletna aplikacija napravljena je po uzoru na Flameshot i u potpunosti
pomoću Claude Code-a (vidi [Zasluge](#zasluge)). Licenca: GPL-3.0-or-later.

## Zašto oštro radi na frakcionalnom skaliranju

- **Snimak u fizičkoj rezoluciji.** Na Cinnamon-u slika se čita direktno iz
  framebuffer-a svakog monitora (`Cinnamon.Eval` → `global.stage.capture`).
  Portal i `org.cinnamon.Screenshot` vraćaju logičku rezoluciju, pa je slika
  mutna. Na monitoru 1600×900 @ 160 % Kadar dobije 2560×1440, a ne 1600×900.
- **Svaki monitor zasebno.** Svaki monitor ima svoj overlay prozor i svoju
  sliku, pa se monitor na 160 % i monitor na 200 % nikad ne preskaliraju jedan
  prema drugom.
- **1 piksel slike = 1 piksel ekrana.** GTK 4 crta preko `wp_fractional_scale_v1`
  u stvarnoj rezoluciji, a overlay mapira sliku tačno na fizičke piksele.
- **Selekcija u fizičkim pikselima.** Isječak se reže tačno po pikselu, a
  oznaka veličine (npr. `960 × 640`) pokazuje stvarnu veličinu slike koja se
  snima.
- **Anotacije su vektori.** Strelice, tekst i ostalo crtaju se ponovo u punoj
  rezoluciji pri izvozu, pa ne ostaje ništa mutno ni nazubljeno.

Radi i u X11 sesiji: Cinnamon snimanje je isto, a clipboard ide preko GTK-a
(`wl-copy` postoji samo na Waylandu). Na X11 nema frakcionalnog skaliranja po
monitoru, pa ni posebnih trikova za njega.

Na drugim okruženjima koristi `grim` (sway, Hyprland i drugi wlroots) ili
xdg-desktop-portal (GNOME, KDE).

## Instalacija

```bash
./install.sh
```

Pravi link `~/.local/bin/kadar` ka ovom folderu (izmjene u kodu važe odmah),
`.desktop` fajl i ikonu. Da tipka **Print** pokreće Kadar umjesto Flameshot-a:

```bash
./install.sh --print-key
```

Zavisnosti (na Mint-u već instalirane): `python3-gi`, GTK 4 (≥ 4.14),
`gir1.2-xapp-1.0` za tray ikonu.

## Korištenje

| Komanda | Šta radi |
|---|---|
| `kadar` ili `kadar gui` | označi područje i crtaj po njemu |
| `kadar full` | svi monitori u clipboard |
| `kadar screen` | monitor ispod miša u clipboard |
| `kadar screen -n 0 -p ~/Slike` | jedan monitor u fajl |
| `kadar launcher` | prozor sa izborom područja, kašnjenja i akcije |
| `kadar config` | podešavanja |
| `kadar tray` | ikona u panelu (lijevi klik = screenshot) |

Opcije kao kod Flameshot-a: `-p PUTANJA`, `-c` (clipboard), `-d MS` (kašnjenje),
`-r` (PNG na stdout), `--pin`, `-u` (upload), a za `gui` još i
`-s/--accept-on-select`, `--region WxH+X+Y` i `--last-region`.

Šta `full` i `screen` rade bez opcija bira se u Podešavanja → General →
"kadar full / kadar screen without options do": kopiraj (podrazumijevano),
sačuvaj u folder, ili oboje. U `config.json` to je `"quick_action"`:
`"copy"`, `"save"` ili `"copy_save"`.

## Alati i prečice (u overlay-u)

| Taster | Alat | Taster | Akcija |
|---|---|---|---|
| P | olovka | Enter | prihvati (podrazumijevano: kopiraj) |
| D | linija | Ctrl+C | kopiraj u clipboard |
| A | strelica | Ctrl+S | sačuvaj |
| S | pravougaonik | Ctrl+P | zakači na desktop (pin) |
| R | popunjeni pravougaonik | Ctrl+O | otvori u aplikaciji |
| C | elipsa | Ctrl+U | upload na Imgur |
| M | marker | Ctrl+Z / Ctrl+Shift+Z | undo / redo |
| T | tekst | Ctrl+A | cijeli monitor |
| B | pikselizacija | Ctrl+M | bez alata (pomjeranje objekata) |
| N | brojač (1, 2, 3…) | Delete | obriši izabrani objekat |
| I | invertovanje boja | Space | panel sa bojom i debljinom |

- **Desni klik**: kolo sa bojama. **Točkić miša**: debljina (kod teksta veličina fonta).
- **Shift** pri crtanju: prava linija pod 45°, kvadrat, krug.
- **Strelice**: pomjeraju selekciju za 1 px (Alt: 10 px), **Shift+strelice** mijenjaju veličinu.
- Bez izabranog alata klik na nacrtani objekat ga izabere. Tada se može
  pomjeriti, obrisati ili mu se može promijeniti boja i debljina.

Pin prozor: povlačenje ga pomjera, točkić zumira, Ctrl+točkić mijenja
prozirnost, dvoklik ili Esc ga zatvara, a desni klik otvara meni.

## Napomene

- Podešavanja su u `~/.config/kadar/config.json`. Pri prvom pokretanju preuzimaju
  se boje, putanja i providnost iz `~/.config/flameshot/flameshot.ini`.
- Kopiranje ide preko `wl-copy`, koji čuva sliku u clipboard-u i nakon što se
  Kadar zatvori. Bez njega (npr. na X11) Kadar ostaje u pozadini dok nešto
  drugo ne kopiraš.
- Selekcija je uvijek na jednom monitoru, kao kod Flameshot-a na Waylandu.
- Upload na Imgur traži vlastiti Client ID (Podešavanja → General). Bez njega
  dugme se ne prikazuje.
- Postavljanje pin prozora na tačno mjesto i "uvijek iznad" radi samo na Cinnamon-u.

## Zasluge

- **Napravljeno po uzoru na Flameshot.** Kompletna funkcionalnost, način rada,
  prečice i komandna linija Kadar-a napravljeni su po uzoru na
  [Flameshot](https://github.com/flameshot-org/flameshot). Kadar je nezavisna
  implementacija i ne sadrži Flameshot-ov izvorni kod. Nije povezan sa
  Flameshot projektom niti ga taj projekat podržava.
- **U potpunosti napravljeno pomoću Claude Code-a.** Sav kod, testovi i
  dokumentacija Kadar-a napisani su pomoću
  [Claude Code](https://claude.com/claude-code)-a, Anthropic-ovog AI agenta za
  programiranje, pod vodstvom Želimira Stevanovića.

## Licenca

Copyright (C) 2026 Želimir Stevanović

Kadar je slobodan softver otvorenog koda pod licencom GNU General Public
License, verzija 3 ili (po vašem izboru) bilo koja kasnija verzija
(GPL-3.0-or-later). Smijete ga koristiti, dijeliti i mijenjati, ali izmijenjene
verzije koje dijelite moraju ostati pod istom licencom. Kadar se isporučuje
BEZ IKAKVE GARANCIJE. Puni tekst licence je u fajlu [LICENSE](LICENSE).
