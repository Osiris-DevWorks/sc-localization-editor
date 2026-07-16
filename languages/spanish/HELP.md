# Smart Citizen: guía de inicio rápido

> Esta página es una traducción proporcionada para tu comodidad. En caso de discrepancia, la versión en inglés prevalece. Estado de las traducciones: `languages/TRANSLATIONS.md`.

## Primera configuración

Al iniciarse, Smart Citizen recarga las personalizaciones de tu sesión anterior y busca tu instalación de Star Citizen: el instalador rellena esta ruta automáticamente, pero puedes cambiarla en la pestaña **Configuración**. Toda la localización original y los datos de DataForge provienen **directamente de tu `Data.p4k` instalado** (sin descargas, sin réplicas de la comunidad), así que extraer una vez es un primer paso obligatorio tras la instalación o tras cualquier parche del juego.

## Modo simple y modo avanzado

Smart Citizen se abre en uno de dos modos, y puedes cambiar en cualquier momento.

- El **modo simple** es una pantalla de dos botones: uno, **Aplicar mejoras**, ejecuta toda la cadena con tu configuración actual (extracción, generación y aplicación, con una copia de seguridad previa de tu archivo del juego); el otro cambia al **modo avanzado**. Es la vía rápida cuando solo quieres aplicar las mejoras sin editar textos a mano.
- El **modo avanzado** es la aplicación completa: la tabla de textos, los filtros, la pestaña Mejoras, la pestaña Configuración y todo lo demás de esta guía.

Elige tu modo predeterminado durante la instalación, o alterna entre ellos dentro de la aplicación. El modo simple usa la última configuración guardada en el avanzado.

## 1. Extraer la localización base desde Data.p4k

Abre la pestaña **Configuración** y haz clic en **Extraer desde Data.p4k**. Esto descomprime el `global.ini` original junto con los XML de entidades de DataForge que usa el generador de mejoras: naves, componentes, armas, misiones, blueprints, etc.

Cuando la extracción termina, el `base.ini` extraído se carga automáticamente en la tabla, fusionado con los archivos de mejoras y tus cambios guardados en `user.ini`.

## 2. Editar textos de localización

- Haz doble clic en cualquier celda de **Valor personalizado** para editar el texto.
- **Valor por defecto**: texto original del `base.ini` extraído de `Data.p4k`.
- **Valor actual**: el valor efectivo antes de tu cambio (base + capas INI importadas).
- **Valor personalizado**: tu edición personal. Se guarda automáticamente con cada cambio y se conserva en `<carpeta de datos>\<canal>\user.ini` (la carpeta de datos por defecto es `Documents\Smart Citizen`, y cada canal de Star Citizen — LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW — tiene sus propios cambios aislados).
- La columna **Estado** indica de dónde procede el valor actual de cada fila:
  - **Modificado**: editaste explícitamente el Valor personalizado.
  - **Mejorado**: generado automáticamente por el proceso de mejoras (superposiciones de estadísticas, etiquetas de blueprints, etc.).
  - **Sin modificar**: texto original del `base.ini`.
  - **Nuevo**: la clave solo existe en tus cambios o en el proceso de mejoras, no en el `base.ini` original.

## 3. Panel de vista previa

El **panel de vista previa** en la esquina superior derecha muestra el texto renderizado de la fila seleccionada. Los tokens de localización del juego se convierten en HTML con estilo para que veas aproximadamente cómo se leerá tu texto en el juego:

- `\n` → salto de línea
- `<EM3>...</EM3>` → encabezado de sección subrayado
- `<EM4>...</EM4>` → énfasis en azul y negrita (normalmente valores de estadísticas)
- `~mission(Name)` → marcador `[Name]` en gris (el juego sustituye el valor real en tiempo de ejecución)

El panel permanece visible en todas las pestañas y refleja la última fila seleccionada en el **Editor de textos**: útil para comprobar el formato de una descripción de misión larga o una entrada de diario antes de aplicar.

## 4. Categorías

Usa el filtro de **Categoría** para centrarte en un dominio:

- **Ships**: nombres y descripciones de naves (`vehicle_Name*`, `vehicle_Desc*`, más las variantes Wikelo/Collector).
- **Ship Items**: escudos, plantas de energía, refrigeradores, motores cuánticos, motores de salto, armas de nave, misiles, bombas, torretas.
- **Missions**: briefings de misión, textos de contratos, descripciones de recompensas.
- **Gear**: armas FPS, armaduras, cascos, trajes, miras.
- **Commodities**: mercancías y materiales de fabricación.
- **Journal**: entradas de diario del juego, estilo Galactapedia.
- **Other**: todo lo demás.

## 5. Búsqueda y filtros

- Usa el **cuadro de búsqueda** para encontrar textos por clave o por contenido.
- Combínalo con los filtros de **Categoría** y **Estado** (Modificado / Mejorado / Sin modificar / Nuevo).
- Marca **Ocultar sin modificar** para ver solo tus propias ediciones.
- Los **cuadros de filtro por columna** bajo cada encabezado afinan la búsqueda dentro de la tabla.
- Haz clic en cualquier encabezado de columna para ordenar. Haz clic en el encabezado **★** para subir los favoritos arriba.

## 6. Naves favoritas

- Haz clic en la columna **★** de cualquier fila de nave para marcarla como favorita.
- Las naves favoritas reciben un prefijo configurable delante del nombre, lo que las sube al principio de la lista de naves del juego.
- Cambia el carácter de prefijo en la pestaña **Mejoras** (por defecto: `*`).

## 7. Aplicar los cambios al juego

Haz clic en **Aplicar mejoras** para escribir tus ediciones en la instalación del juego. Antes de sobrescribir nada, se crea una copia de seguridad con fecha y hora del `global.ini` actual en `<carpeta de datos>\<canal>\backups\`.

El color del botón te dice en qué punto estás: **rojo** significa que algo ha cambiado desde tu última aplicación (una edición, una regeneración, un cambio de idioma o de canal) y el juego aún no lo tiene; **verde** significa que el juego ya coincide con lo cargado, y el botón queda desactivado porque no hay nada que rehacer. La misma convención rojo/verde se aplica a **Generar mejoras** y **Aplicar cambios de etiquetas** en la pestaña Mejoras. Si cierras la aplicación con el botón Aplicar todavía en rojo, Smart Citizen te pregunta si aplicar ahora o salir sin aplicar, para que el trabajo sin aplicar nunca se pierda en silencio.

Smart Citizen también estampa una pequeña marca de agua en el texto de versión del lanzador (`Frontend_PU_Version`), añadiendo `| Localizations Enhanced with Smart Citizen v{VERSION}`. Así confirmas en el juego que tu loc-pack está activo: mira la etiqueta de versión en el menú principal de Star Citizen. La marca se reescribe con cada aplicación, así que nunca se acumula entre versiones.

## 8. Restaurar una copia de seguridad

Abre el menú **Más** de la barra de herramientas y elige **Restaurar copia** para volver a una versión anterior. Smart Citizen conserva hasta **5 copias de seguridad automáticas**; la más antigua se elimina a medida que se crean nuevas.

## 9. Limpiar la localización

Abre el menú **Más** y elige **Limpiar localización** para borrar el `global.ini` personalizado del directorio del juego y devolver el juego a su texto por defecto (original). Tus cambios guardados en `<carpeta de datos>\<canal>\user.ini` quedan intactos y pueden reaplicarse en cualquier momento.

## 10. Importar un INI

Usa **Importar INI** en la pestaña **Configuración** (también disponible en el menú **Más** de la barra de herramientas) para incorporar un archivo INI existente a tus cambios. Un diálogo de resolución de conflictos te deja decidir, clave por clave: **mantener el actual**, **usar el importado**, **añadir después**, **añadir antes**, o introducir un valor **personalizado**.

## 11. Exportar un Loc-Pack

Abre el menú **Más** y elige **Exportar INI…** para empaquetar el `global.ini` actualmente aplicado en un único zip, `SmartCitizen-LocPack-{canal}-{AAAAMMDD}.zip`, que cualquiera puede soltar en su carpeta `StarCitizen\<canal>\data\Localization\english\` para usar el mismo loc-pack sin instalar Smart Citizen. Útil para compartir configuraciones con amigos o con tu organización.

## 12. Restablecer user.ini

Usa **Restablecer user.ini** en la pestaña **Configuración** para borrar todas tus ediciones personales del canal activo. Una confirmación evita clics accidentales, y antes se guarda automáticamente una copia del `user.ini` actual en `<carpeta de datos>\<canal>\backups\`: el restablecimiento es recuperable si cambias de opinión.

## 13. Tras las actualizaciones del juego

Cuando Star Citizen se actualiza, tus ediciones se conservan en `<carpeta de datos>\<canal>\user.ini`. Vuelve a ejecutar **Extraer desde Data.p4k** para obtener los textos originales del juego parcheado: la tabla se recarga automáticamente y tus personalizaciones se reaplican encima.

## 14. Cambiar de idioma

Elige un idioma en el menú **Idioma** de la pestaña **Configuración** (junto a Canal). El cambio afecta tanto a la interfaz de la aplicación como a los textos del juego en la tabla:

- **Inglés** (el predeterminado) usa los textos originales extraídos de tu propio `Data.p4k`.
- **Los demás idiomas** descargan el `global.ini` traducido por la comunidad para ese idioma y lo superponen a la base en inglés: cualquier texto que la traducción no cubra vuelve al inglés en lugar de desaparecer. La descarga se guarda en caché por idioma; volver a un idioma ya usado reutiliza la caché.
- **Las mejoras permanecen en inglés.** Los bloques de estadísticas, etiquetas y detalles de misión se generan a partir de los datos del juego y mantienen su forma en inglés sobre la prosa traducida. Una línea mixta (por ejemplo, un nombre de rol en español dentro de un bloque de estadísticas en inglés) es lo esperado, no un error.
- **Asignar archivo de idioma** (pestaña Configuración) permite apuntar un idioma a otra URL de `global.ini`, por ejemplo tu propio fork de una traducción comunitaria. Tu URL gana sobre la predeterminada incluida.
- Algunos textos de la interfaz solo se actualizan tras reiniciar la aplicación. Los textos de la tabla se recargan de inmediato.

Al aplicar, la aplicación escribe en la carpeta de idioma correspondiente de tu instalación del juego y establece `g_language` en `user.cfg`, para que el juego cargue el archivo correcto.

¿Quieres ayudar a traducir? El estado de las traducciones por idioma se sigue en `languages/TRANSLATIONS.md` del repositorio, y preferimos mil veces tus palabras a las de una máquina. Escríbenos en el Discord.

## 15. Actualizaciones de la aplicación

Smart Citizen comprueba si hay una versión nueva cada vez que arranca. Cuando hay una disponible, las notas de la versión aparecen en una ventana con dos opciones:

- **Actualizar ahora** descarga el nuevo instalador, Windows pide permiso, y Smart Citizen se cierra, se actualiza y se vuelve a abrir en la versión nueva. Tus ediciones, copias de seguridad y configuración quedan intactas.
- **Más tarde** te mantiene en la versión actual; la pregunta volverá en el próximo arranque.

También puedes comprobarlo manualmente en cualquier momento con **Buscar actualizaciones** en la pestaña Configuración. Las versiones portables muestran en su lugar un botón **Abrir página de la versión**, ya que no hay instalador que ejecutar: descarga el zip nuevo y descomprímelo sobre la carpeta antigua.

## Pestaña Mejoras

- Activa superposiciones de estadísticas que añaden datos numéricos a las descripciones: velocidad SCM, PV de escudo, DPS, capacidad de carga, estadísticas de rayo de los láseres de minería (Fractura / Extracción), rendimiento de las herramientas de recuperación de mano, listas de blueprints, XP de misión y más. El XP de misión también indica la vía de reputación que alimenta (ej.: `750 XP (Hauling)`), los contratos de escaneo/minería de Battaglia llevan una etiqueta `[RS ####]` con la firma de recurso base del mineral objetivo, y el diario Mining Compendium lista la RS base de cada mineral junto a sus ubicaciones de minado.
- **Consumibles médicos**: añade una línea de efecto en lenguaje claro a los inyectores CureLife básicos (MedPen, OxyPen, AdrenaPen y compañía), para que la descripción diga lo que hace realmente el inyector en lugar de limitarse a su trasfondo.
- **Mostrar estadísticas encima de la descripción**: coloca el bloque de estadísticas al principio de la descripción en lugar del final, para que los números sean lo primero que leas en el juego.
- Activa o desactiva cada categoría de mejoras de forma independiente.
- Configura el carácter de prefijo de las naves favoritas.
- **El seguimiento de blueprints adquiridos** se ha movido a su propia pestaña **Rastreador de blueprints**; consulta la sección siguiente.
- **Creador de etiquetas**: personaliza las etiquetas entre corchetes de los nombres de componentes, misiles, armas de nave y mercancías. Reordena los elementos con ▲/▼, desactiva elementos individuales, cambia la longitud de la abreviatura (`M` / `MIL` / `Military`), elige el separador (ninguno, guion, espacio, etc.) y los corchetes (cuadrados, redondos, ninguno, etc.), y decide si la etiqueta va antes o después del nombre. Los componentes tienen además un elemento **Type** opcional (Escudo, Refrigerador, Planta de energía, etc.), desactivado por defecto. Las mercancías tienen un elemento **Usage** que muestra a qué se destinan sus materiales de fabricación. Haz clic en **Aplicar cambios de etiquetas** para guardar y regenerar. (**Generar mejoras** también guarda primero cualquier cambio de etiqueta pendiente, para que un ajuste sin guardar nunca se escape de una regeneración.)
- **Títulos de misión** (pestaña Creador de etiquetas): antepón a los títulos de las misiones de transporte su ruta. Elige la posición (antes, después, o sustituyendo el título), la flecha de la ruta (`>`, `->`, `to`, o las formas `->-`/`->=`/`=>-`/`=>=` que distinguen un punto único de varios en cada extremo), el separador de título, y cuánto detalle mostrar de la ubicación (dirección completa por defecto; el nombre corto puede no mostrarse en misiones raras), con vista previa en vivo. Un transporte se lee entonces `Area18 > Lorville - <título original>`, para ver el trayecto de un vistazo en la lista de contratos, y los transportes con varias paradas listan sus destinos (`Area18 > Lorville, New Babbage`). Dos opciones independientes recortan el título original: **Acortar títulos originales** aplica abreviaciones de frases seleccionadas (p. ej. «Local Shipment Route» → «Route», más el tratamiento de los prefijos de rango y de la familia Ling), y **Acortar tamaños de carga** abrevia los tamaños («Extra Small» → «XS»). Casillas individuales dan un control más fino — quitar «Cargo» o «Haul», eliminar «Rank», o subrayar los transportes «Direct» para destacarlos — de modo que la ruta y las etiquetas quepan incluso en títulos largos.
- **Rótulos de misión**: personaliza los encabezados de sección de los bloques de mejora de misión (MISSION DETAILS, POTENTIAL BLUEPRINTS, ITEM REWARDS, BLUEPRINT DATA), el rótulo de XP mostrado en misiones sin rango de reputación específico (por defecto «Rep»), y la etiqueta de énfasis (EM3 = subrayado, EM4 = color) de los encabezados.
- **Campos de detalles de misión**: muestra u oculta individualmente cada línea del bloque MISSION DETAILS (tipo de misión, dificultad, apariciones, reputación, blueprints y la etiqueta de título `[BP]`), para que tus descripciones de misión lleven solo los datos que te importan.
- Haz clic en **Generar mejoras** para extraer los datos de DataForge de `Data.p4k` y reconstruir los archivos INI de mejoras. Los parches declarativos de `patches/` se reaplican de forma idempotente en cada regeneración, para que los errores de datos conocidos de CIG sigan corregidos sin esperar un parche del juego.

## Pestaña Rastreador de blueprints

Lleva el control de qué blueprints de fabricación ya posees, y míralo reflejado en el juego: los objetos adquiridos reciben una etiqueta azul `[Owned]` en las listas POTENTIAL BLUEPRINTS de las misiones, de modo que un contrato te dice de un vistazo qué te queda por conseguir.

- **Dos listas, un transbordo.** Los blueprints disponibles a la izquierda, tu colección a la derecha. Selecciona elementos y muévelos con los botones de flecha. La colección persiste entre sesiones.
- **Encuentra rápido.** Un cuadro de búsqueda filtra ambas listas, y los filtros **Misión / Tipo / Clase / Tamaño / Grado** reducen la lista de disponibles según la misión de origen del blueprint y el tipo de objeto (armadura, arma FPS, objeto de nave, etc.).
- **Escanear registros en busca de blueprints adquiridos** rellena la colección automáticamente: lee los archivos de registro de Star Citizen en busca de los blueprints recibidos en el juego y los marca como adquiridos. Solo se importan los blueprints recibidos desde el último escaneo, así que repetirlo en cualquier momento apenas cuesta. El escaneo necesita que la ruta de instalación de Star Citizen esté configurada en la pestaña Configuración.
- **Aplicar etiquetas [Owned]** vuelve a tejer las etiquetas `[Owned]` en tus textos cargados tras cambiar la colección. Como los demás botones de acción, se pone **rojo** cuando tu colección tiene cambios que la tabla aún no ha incorporado y **verde** cuando todo está sincronizado.
- La columna **Adquirido** de la tabla de textos sigue mostrando una estrella y ordenando primero los adquiridos, pero ahora es de solo lectura; la colección se gestiona desde esta pestaña.

## Pestaña Configuración

- **Apariencia**: elige el tema de la aplicación (ver más abajo).
- **Instalación de Star Citizen**: ruta a tu directorio LIVE; detectada automáticamente en la instalación, editable aquí. El menú **Canal** elige qué canal lee y escribe la aplicación, y el menú **Idioma** cambia la aplicación y los textos del juego (ver *Cambiar de idioma* más arriba).
- **Datos de Smart Citizen**: carpeta para `user.ini`, cachés, extracción de DataForge, INI de mejoras generados y copias de seguridad. Por defecto `Documents\Smart Citizen`; sácala de OneDrive si la extracción o la limpieza de caché van lentas.
- **Localización base (extracción P4K)**: haz clic en **Extraer desde Data.p4k** para descomprimir la localización original y los datos de entidades de DataForge directamente desde tu juego instalado. Es la única fuente de los textos base y de los datos de mejoras.
- **Importar INI**: incorpora un archivo INI existente a tus cambios mediante el diálogo de resolución de conflictos.
- **Restablecer user.ini**: borra todas tus ediciones personales del canal activo. Pide confirmación y hace una copia de seguridad automática del `user.ini` actual antes de limpiar.
- **Restaurar user.ini**: devuelve tus ediciones personales a una instantánea anterior. Smart Citizen conserva copias rotativas de `user.ini` (hasta 5, tomadas automáticamente antes de cada cambio): si una importación o edición sale mal, elige una versión anterior y recupera tus textos. La restauración es a su vez reversible: el archivo actual se guarda primero.

## Pestaña Registro

- Registro de la aplicación en tiempo real.
- Filtra por nivel, activa el desplazamiento automático y **exporta** el registro para diagnóstico o informes de errores.

## Temas

Elige un tema en **Configuración → Apariencia**:

- **Predeterminado**: SCLE, un tema ciber azul marino inspirado en la interfaz mobiGlas de Star Citizen.
- **Claro / Oscuro**: temas de interfaz clásicos.
- **ODW**: la firma de Osiris DevWorks, grafito marino con dorado antiguo.

## Barra de estado

Muestra el recuento de entradas cargadas / modificadas y el estado de cualquier tarea en segundo plano (extracción, generación, aplicación).

## Visita guiada

Haz clic en el botón **Tutorial** de la barra de herramientas en cualquier momento para repetir la visita guiada: un recorrido paso a paso del flujo de trabajo principal con indicaciones en pantalla señalando cada control. La visita también se ejecuta automáticamente la primera vez que inicias una versión nueva, para que una instalación recién hecha nunca empiece a ciegas. Pulsa **Omitir** en cualquier momento para cerrarla.

## Pestaña FAQ

La pestaña **FAQ** responde a las preguntas que más nos hacen, directamente en la aplicación: qué archivos toca Smart Citizen, si pueden banearte por usarlo, por qué Windows señala el instalador, y cómo deshacer tus cambios. Consúltala primero; si tu pregunta no está cubierta, el Discord está a un clic.

## Atajos de teclado

- **Ctrl+Shift+C**: copiar las filas filtradas al portapapeles (formato clave=valor).

## Solución de problemas

- **Nada en la tabla**: comprueba que **Extraer desde Data.p4k** ha terminado y que la recarga posterior a la extracción ha concluido; después revisa la pestaña **Registro** en busca de errores de lectura.
- **Mejoras vacías o con elementos ausentes**: ejecuta **Generar mejoras** desde la pestaña Mejoras; necesita una caché de DataForge (haz clic antes en **Extraer desde Data.p4k** si aún no lo has hecho).
- **Aplicar mejoras falla**: confirma la ruta de instalación de Star Citizen en la pestaña **Configuración** y que el juego no está en ejecución.
- **Datos obsoletos tras una actualización del juego**: vuelve a ejecutar **Extraer desde Data.p4k** y después regenera las mejoras.

## Problemas conocidos

Algunas anomalías en textos de misión tienen su origen en los propios datos de Star Citizen (referencias erróneas de claves de localización en los registros de contratos de CIG). El juego lee los contratos desde su propio `Data.p4k` en tiempo de ejecución, así que Smart Citizen no puede cambiar qué clave consulta el juego: solo puede editar el *texto* de cada clave. Cuando resulta práctico, sorteamos estos errores fusionando el contenido previsto en la clave que el juego realmente lee.

- **Dosier de Jorrit, «Updated Power Usage Data» muestra el texto de Energy Anomaly**: CIG Issue Council [STARC-176797](https://issue-council.robertsspaceindustries.com/projects/STAR-CITIZEN/issues/STARC-176797). El contrato `Hockrow_FacilityDelve_P2M4-Stanton4_Repeat` de CIG apunta su parámetro `Description` a `@Hockrow_FacilityDelve_P2M1_Repeat_desc` en lugar de a su propio `P2M4_Repeat_desc`, así que los jugadores ven en el juego el texto de ambientación de Energy Anomaly de P2M1 en una misión titulada «Power Usage Data». Smart Citizen lo sortea en dos pasos, ambos declarados en `patches/contracts/contractgenerator/mercenary_guild/hockrowagency/hockrowagency_facilitydelve.patch.json`:
  1. Una edición del XML de DataForge para que nuestro generador de mejoras asocie la lista correcta de blueprints de P2M4 (Corbel Smolder, Geist Rogue/Whiteout) a `P2M4_Repeat_desc` en lugar de reducirla a la de P2M1.
  2. Un arreglo de texto que añade el contenido completo de `P2M4_Repeat_desc` (su texto de ambientación más su propia lista de blueprints) al final de `P2M1_Repeat_desc`, separado por un divisor rotulado. Como el juego lee el puntero defectuoso y consulta `P2M1_Repeat_desc` para ambos contratos, el contrato P2M4 ahora muestra su contenido previsto. Los jugadores de P2M1 ven el bloque de P2M4 como un apéndice rotulado tras su propia descripción: más ruidoso, pero ambos contratos muestran ya la lista de blueprints correcta y el texto de ambientación correcto.

  Cuando CIG corrija STARC-176797, el archivo de parche entero podrá borrarse y la siguiente regeneración volverá a producir descripciones limpias y separadas.

## Comentarios, errores y votación de funciones

- **Informa de errores, comparte configuraciones personalizadas y vota las próximas funciones** en el canal de Discord dedicado a Smart Citizen: [Discord de Osiris DevWorks, comentarios y votación #smart-citizen](https://discord.com/channels/1438175448420057323/1472394204347895890) (primero hay que unirse al servidor de Osiris DevWorks: [invitación](https://discord.gg/BNzRegKZ7k)). La priorización de funciones se guía por las reacciones y votos de ese canal: cuanta más demanda tiene una petición, antes llega.
- Al informar de un error, adjunta el registro (pestaña Registro → **Exportar**) y menciona tu versión de Star Citizen, para que podamos distinguir los problemas propios de los cambios del juego.
