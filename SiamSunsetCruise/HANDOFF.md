# Siam Sunset Cruise — handoff for the next Claude

Paste this whole file to Claude on the other PC and say "continue this".

## What this is
- Owner's real site: https://cruise-booking-three.vercel.app/ (Thai, compares 9 Chao Phraya dinner boats).
- We redesigned it as ONE scroll-driven three.js page with a 3D boat sailing from sunset to night: `siam-sunset-river.html`.
- The owner now cares most about the **yacht looking real**: a 101 m dinner-cruise superyacht, after a Gemini concept picture
  (white superstructure, navy hull, pool, helipad at the bow, beach club at the stern).
- The owner likes short, simple answers. Explain like they are 5.

## Links (jirateepdev@gmail.com account)
- 3D yacht viewer: https://claude.ai/artifact/39JCkqiySiiUqoxWRdkb3R — `yacht-preview.html` + `boat.json`, `boat-ao.jpg`, `sky-sunset.jpg`, `wood-grain.jpg`.
- Photo gallery (8 Cycles renders): https://claude.ai/artifact/4V4yeMwoGNEuuBo28N8XmQ — `yacht-gallery.html` + `renders/*.jpg`.
- Main site: https://claude.ai/artifact/1DwMwQKHi7pQns1X3RErZ4 (still the old 34 m yacht; see "Not done").
- To update an artifact from another conversation: `Artifact` `action: "read"` it first, then publish with its `url`.
  Artifacts don't serve .glb, so the glTF is JSON with its data inlined (`boat.json`).

## Keep exactly
- Name: Siam Sunset Cruise. LINE @siamsunsetcruise, phone 089-777-6655, license ททท. 11/09988, open daily 08:30–22:30.
- Thai language on the main site. Fonts: Chonburi (titles) and IBM Plex Sans Thai Looped (body).
- Colours: --ink #0a0e14, --paper #f4ead9, --marigold #f5a524.

## The yacht model (`build_boat.py`, Blender 5.2, no hand modelling: edit the script and rebuild)
```
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python build_boat.py
```
- Writes `boat.json` (~9 MB) and `boat-ao.jpg` (baked AO). Add `-- preview=<folder> views=hero,heli,dinner` for quick Cycles stills
  (views: hero, side, bow, top, stern, ref, aft, bowclose, heli, dinner).
- Blender space: bow +Y, up +Z, waterline 0. Hull Y -47..51 (98 m + platform), decks D1..D5 = 4.4 / 7.7 / 11.0 / 14.3 / 17.4.
- Has: raked bow, navy boot stripe, gold pinstripes, grouped hull windows, 4 stepped deckhouses with glazing, pool, sun deck hardtop,
  mast and domes, beach club with twin stairs, jet skis, limo tender alongside, raised helipad on a pedestal (y 38.5, z 9.8) with a
  helicopter, ~50 guests at the dinner tables (76 seats), festoon string lights, life-raft canisters, anchor chains.
- Material names are the contract with the pages: each page's `BY_NAME` swaps them for live materials. A new name (like `Skin`)
  needs adding to `BY_NAME` and to the aoMap list in both pages.

## The 3D viewer (`yacht-preview.html`, three.js r128)
- Opens on **Sunset**: the real Poly Haven photo `sky-sunset.jpg` (HDRI "Small Harbour Sunset", CC0, saved as LDR JPG) is the
  background and the PMREM environment. Day and Night use the drawn sky shader.
- Sky shader must keep `#include <tonemapping_fragment>` + `<encodings_fragment>`, or glass and water go black.
- Night: windows glow, nav lights, and a cyan underwater-light halo along the hull, drawn in the water shader.
- Deck planks: canvas texture with the real wood photo `wood-grain.jpg` overlaid.

## Photo-real renders (the owner's favourite)
The web 3D can't look like a photo, but Cycles renders of the same model do.
- `render-scene.blend` (26 MB, everything packed) is the render scene: model with bevel + weighted normals, clear-coat paint,
  plate seams, tinted glass, teak, Ocean modifier sea, hull foam strip, underwater glow strip, sunset HDRI, glare + vignette.
- `render_shots.py` renders the 4 views (bow, side, stern, helipad) into `renders/`:
  ```
  & "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" render-scene.blend --background --python render_shots.py
  & "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" render-scene.blend --background --python render_shots.py -- night
  ```
  Options: `only=bow,side`, `samples=512`. About 30 s a picture on an RTX 3060 (it picks the GPU itself; CPU is much slower).
- After a model change: rebuild `boat.json`, re-import it into the scene (replace the `Boat` object, then re-apply the bevel
  and the material tweaks), and re-render. The material tweaks were done by hand in the session, not in a script.
- The owner's 12-step realism checklist (what each render pass should cover): load model → navy hull that stays navy →
  panel seams → tinted glass with warm interiors → real teak → soft cushions / linen → darker sea with foam → side-lit sun,
  hide the hill → photographer's camera → 4 sunset renders → 4 night renders → gallery.

## Tools on this PC (set up again on the other PC if you want them)
- **BlenderMCP** (github.com/ahujasid/blender-mcp) lets Claude drive a live Blender: Poly Haven assets, Rodin AI, Sketchfab.
  - Add-on: `addon.py` installed in Blender, then in the 3D view press N → BlenderMCP tab → port **9877** → Connect.
    (The other "Blender" MCP extension uses 9876.)
  - Claude side: `claude mcp add blender-mcp --scope user -e BLENDER_PORT=9877 -e DISABLE_TELEMETRY=true -- uvx blender-mcp`.
    Needs `uv` (the owner installs it; the auto-mode safety check blocks Claude from running the installer).
  - Usage data sharing is switched off.
  - Rodin's shared free trial key was out of credits. Sketchfab needs the owner's own free API key (not set yet).
- Poly Haven assets are CC0, free for business use.

## Local preview (no node/python on this PC)
```
powershell -NoProfile -ExecutionPolicy Bypass -File serve.ps1 -Root . -Port 8765
```
Then open http://localhost:8765/yacht-preview.html, yacht-gallery.html or siam-sunset-river.html (file:// does not animate).

## Not done / next steps
- **Main site still set for the 34 m yacht.** `siam-sunset-river.html` loads the new 101 m `boat.json`, so its camera keyframes,
  flag position (now staff at (0, 6.1, 47.95) in page space), nav-light glows, warm lights and water pool/streak sizes are
  all wrong scale. Its live artifact (1DwMwQKHi7pQns1X3RErZ4) still has the 34 m files.
  Option the owner liked: use the Cycles renders on the site instead of, or next to, the live 3D.
- Helipad close-up shows the helicopter and pad are still simple shapes. No glasses or candles on the tables, and no bow wake
  (the yacht is at anchor).
- The sky photo is a hilly lake, not Bangkok. A Chao Phraya-like HDRI, or a city-at-night one, would suit better.
- Only checked on desktop. Phone not checked for the viewer or the gallery.
