# Prompts para las fotos reales — campañas paid GuruSup

Dos fotos gemelas: **mismo chico, mismo encuadre, misma distancia de cámara**.
Lo único que cambia es el escenario (aeropuerto → hotel) y la temperatura de luz (fría → cálida).

## Recomendación: generar como díptico (consistencia garantizada)

La forma más fiable de que el chico sea el mismo en ambas fotos es generar **una sola imagen
en dos paneles** y luego recortar cada mitad. Prompt maestro (inglés, funciona mejor en
Midjourney / Flux / GPT-Image / Firefly):

```
Split-screen diptych photograph, two panels side by side, SAME young man in his
mid-20s wearing a grey hoodie and jeans, same camera angle and distance in both
panels, editorial advertising photography.

LEFT PANEL: he is slumped asleep across a row of black airport waiting-room
chairs at night, exhausted and uncomfortable, hugging his jacket, a coral-red
suitcase standing next to the chairs, out-of-focus airport departures board in
the background with red "CANCELADO" status text, empty clean terminal, cold
blue-grey ambient lighting, melancholic mood.

RIGHT PANEL: the same man sleeping peacefully in a hotel bed with white crisp
bedding, relaxed expression, warm soft bedside lamp light, the same coral-red
suitcase standing out of focus in the background near the door, minimal calm
hotel room, cozy warm amber tones.

Shot on 35mm lens, shallow depth of field, eye-level camera height, cinematic
color grading, minimal uncluttered composition, negative space at the top of
each panel, realistic skin texture, no text overlays except the blurred
departures board. --ar 16:9 --style raw
```

Después: recortar cada mitad a vertical y colocarla en la plantilla
(`foto-aeropuerto.jpg` y `foto-hotel.jpg`).

## Alternativa: dos generaciones separadas

Generar primero la Foto 1, y usar referencia de personaje para la Foto 2
(Midjourney: `--cref <url foto 1> --cw 100`; GPT-Image/Flux: adjuntar la foto 1
y pedir "the same man, same framing").

### Foto 1 — Aeropuerto (SIN GuruSup)

```
Editorial advertising photo, vertical 4:5. A young man in his mid-20s, grey
hoodie, slumped asleep across a row of airport waiting-room chairs late at
night, exhausted, head resting on his arm. A coral-red suitcase stands beside
the chairs. In the background, out of focus, an airport departures board with
red "CANCELADO" text — clearly an airport, but minimal and uncluttered, empty
terminal. Cold blue-grey lighting, cinematic, shallow depth of field, 35mm,
eye-level camera, negative space at the top. --ar 4:5 --style raw
```

Variante (si las sillas dan problemas): `...sleeping on the terminal floor,
leaning against his coral-red suitcase, ...`

### Foto 2 — Hotel (CON GuruSup)

```
Editorial advertising photo, vertical 4:5, SAME man as reference image, same
camera distance and eye-level framing. He is sleeping peacefully in a hotel bed,
white crisp bedding, relaxed face, one arm over the duvet. Warm soft bedside
lamp light, amber tones. The same coral-red suitcase stands in the background
near the door, out of focus, secondary. Minimal calm hotel room — it should
read as a hotel (headboard, neutral decor), not a home. Negative space at the
top. --ar 4:5 --style raw
```

## Dirección de arte (vale también para shooting con fotógrafo)

- **Protagonista**: chico joven (~25), vestuario idéntico en ambas fotos (sudadera gris).
- **Maleta coral** (`#FF5A5F`, el color de marca) en ambas fotos: es el hilo conductor
  visual que dice "mismo viajero, misma noche". En la foto 1 protagonista-secundaria,
  en la foto 2 al fondo y desenfocada.
- **Luz**: foto 1 fría (azul-gris, fluorescente de terminal); foto 2 cálida (lamparita ámbar).
  El contraste de temperatura ES el mensaje.
- **Composición limpia**: terminal vacía, sin multitudes, sin carteles ajenos; habitación
  de hotel minimalista. Dejar **aire en el tercio superior** (ahí van los chips
  SIN/CON GURUSUP) y, en la plantilla A, evitar elementos clave en el centro del
  encuadre (ahí se apoya la tarjeta de chat).
- **Mismo objetivo y altura de cámara** en ambas (35 mm, altura de ojos) para que el
  split se lea como un espejo.
- **Texto en escena**: solo el panel "CANCELADO" desenfocado. Nada más.

## Colocación en plantilla

1. Guardar como `foto-aeropuerto.jpg` y `foto-hotel.jpg` en esta carpeta.
2. Abrir `plantilla-a-foto.html` / `plantilla-b-foto.html` (las cogen automáticamente).
3. Regenerar PNGs: `node render.js` (los scrims de legibilidad ya están aplicados).
