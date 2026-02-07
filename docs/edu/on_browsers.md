# On Browsers: De Cero vs. Funcional

Este documento resume dos caminos distintos para construir un navegador: uno desde cero (aprendizaje y control) y otro funcional basado en un motor existente (uso diario y privacidad real).

## Escenario A: Navegador Desde Cero (Toy / Educativo)

Objetivo: aprender cómo funciona un navegador y tener control total del stack, aceptando que no será usable en la web moderna por bastante tiempo.

Alcance recomendado (realista):
- HTML básico: `h1..h6`, `p`, `a`, `img`, `ul/ol/li`.
- CSS básico: colores, tamaños de fuente, márgenes, padding.
- Layout: solo bloques, sin flex/grid al inicio.
- Red: HTTP GET simple, redirecciones, manejo básico de errores.
- Sin JavaScript al principio.

Fases sugeridas:
1. Render de HTML + CSS básico.
2. Navegación con links y un historial mínimo.
3. Inputs/formularios simples.
4. Expansión gradual (más CSS, luego algo de JS).

Ventajas:
- Máximo aprendizaje y propiedad.
- Diseño y arquitectura totalmente tuyas.

Limitaciones:
- Web real no va a funcionar.
- Mucho trabajo antes de ser utilizable.

## Escenario B: Navegador Funcional Basado en Motor Existente

Objetivo: crear un navegador usable en el día a día con enfoque fuerte en privacidad.

Motores posibles:
- Firefox/Gecko (más independencia).
- Chromium (más compatibilidad, más monocultura).

Fases sugeridas:
1. Desactivar telemetría y diagnósticos.
2. Bloqueo de trackers y cookies de terceros por defecto.
3. UI de privacidad clara (permisos por sitio, panel de rastreadores).
4. Construcción reproducible y releases verificables.

Ventajas:
- Usable rápido.
- Impacto real en privacidad personal.

Limitaciones:
- Dependencia de upstream.
- Mantenimiento continuo para parches y compatibilidad.

## Cómo Elegir

Si quieres aprendizaje profundo y control: empieza por “desde cero”.  
Si quieres un navegador para usar pronto y que reduzca vigilancia: usa un motor existente y endurece su configuración.

Lo ideal es tratarlos como proyectos complementarios: un “toy browser” para aprendizaje, y un “privacy fork” para uso real.
