# Siam Sunset Cruise — handoff for the next Claude

Paste this whole file to Claude on the other PC and say "continue this".

## What this is
- Owner's real site: https://cruise-booking-three.vercel.app/ (Thai, compares 9 Chao Phraya dinner boats).
- We redesigned it as ONE scroll-driven three.js page with a 3D boat sailing from sunset to night.
- Live version (jirateepdev@gmail.com account, has phone fixes): https://claude.ai/artifact/1DwMwQKHi7pQns1X3RErZ4
  - Read it with the Artifact tool (`action: "read"`). To update it, publish with that `url`.
- Old link from the other PC's account (no phone fixes): https://claude.ai/artifact/XmjmDFE24ZiVNM96iNNhV5
- Local copy: `siam-sunset-river.html` (this folder). It is one self-contained file.

## Keep exactly
- Name: Siam Sunset Cruise. LINE @siamsunsetcruise, phone 089-777-6655, license ททท. 11/09988, open daily 08:30–22:30.
- Thai language. Fonts: Chonburi (titles) and IBM Plex Sans Thai Looped (body).
- Colours: --ink #0a0e14, --paper #f4ead9, --marigold #f5a524.

## How the page works
- three.js r128 from cdnjs. ACESFilmic tone mapping, exposure 1.2. Keep linear output: sRGB made it washed out.
- Custom shaders:
  - Sky (shared `SKY_FN`): fbm clouds, sun, moon, haze.
  - Water: sine-wave normals, Fresnel reflection, boat wake, night light pool, city reflections.
- Scroll story: 7 chapters, each set by clock minutes (start 990, board 1005, sunset 1070, dinner 1140, lights 1230, choose 1275, book 1305).
  - Each chapter has its own camera keyframes, sky keyframes (`KEYS`) and panel side.
  - `setViewOffset(side*0.2)` shifts the boat away from the text panel.
- The world group moves +z by `pS*560`, which makes the boat look like it is sailing.
- Boat is fully procedural:
  - Hull: ExtrudeGeometry from `hullShape()`.
  - Details: gold `trim()`, arched window textures (`archPath`), portholes, Thai `gable()` pavilion roof, lanterns, nav lights.
  - Night brightness comes from `tod.n`.
- `BOATS` array holds the 9 boats and their data. `setPalette()` recolours the boat when you pick one.
- During the hero chapter you can drag to orbit the boat.

## Local preview (no node/python on this PC)
```
powershell -NoProfile -ExecutionPolicy Bypass -File serve.ps1 -Root . -Port 8765
```
Then open http://localhost:8765/siam-sunset-river.html.
Opening the file directly (file://) does not animate properly.

## Status / next steps
- Desktop (1280×720) has been checked and looks good.
- Phone (375×812) checked locally, all 7 chapters. Fixed: hero text was below the first screen, boat was cut off (camera now pulls back 2.2×), boat list rows overlapped (`flex: none`).
  - On phones, the panels stack at the bottom and the clock sits top-right.
  - Published to the new link above.
- The owner likes short, simple answers. Explain like they are 5.
