# Project Overview — Asistente de reservas de salas (Cubo Itaú)


## 1. Resumen

El desafío consiste en un chatbot que gestiona las reservas de las salas de reuniones A–E de la oficina de Cubo Itaú.
El usuario inicia sesión (User1 o User2 dados en la consigna) y habla en español con el agente para consultar qué salas están libres, ver la agenda de una sala, reservar y cancelar sus reservas. El agente interpreta el pedido y llama a la herramienta correspondiente, que ejecutan la lógica real contra PostgreSQL.
Junto al chat, una grilla muestra la disponibilidad de todas las salas para el día elegido, solo a modo de visualización.

Demo: https://d2bnvip7mwuw0n.cloudfront.net (Nombre de usuario: User1 / Contraseña: TechnicalChallengePromtior)

| Componente | Tecnología |
|---|---|
| API y frontend | FastAPI + un único `index.html` (HTML/CSS/JS sin frameworks) |
| Agente | LangGraph (`StateGraph` propio) + tools de LangChain |
| LLM | Groq (`openai/gpt-oss-20b`) vía `langchain-groq` |
| Datos | PostgreSQL con SQL directo (psycopg 3) |
| Autenticación | JWT + bcrypt |
| Deploy | AWS EC2 + Docker Compose, detrás de CloudFront (HTTPS) |


## 2. Inicio del desafío

Lo primero fue leer bien la consigna y anotar todo lo que había que entregar. Con eso se
armó un esquema del agente y de las tools que iba a necesitar, tales como crear una reserva, ver las salas libres, ver la agenda de una sala y cancelar.

Antes de comenzar con el LLM se construyeron las reglas y la base de datos, para probarlos con tests sin depender de lo que responda el modelo. El agente se sumó luego, cuando el servicio de reservas ya funcionaba.

Al leer la consigna también aparecieron casos que no estaban definidos, por ejemplo qué
pasa si alguien reserva en el pasado o un sábado a la noche. Para esos casos se agregaron
reglas propias, que se explican junto con el resto en la sección 4.

### Paso a paso

El trabajo se dividió en PRs chicas, una por etapa, desde el setup hasta el deploy. Una vez
desplegada la demo, al probarla aparecieron problemas que no estaban en el plan y se
resolvieron en PRs aparte. Las cuales fueron:
1. Estructura, dependencias, configuración, pytest, Postgres en Docker
2. Reglas de negocio en `rules.py` y generación de slots
3. Esquema SQL, crear, cancelar y listar reservas, disponibilidad y agenda
4. Login con JWT y bcrypt
5. Documentación del código
6. Tools, prompt, grafo de LangGraph y endpoint `/chat`
7. Horario de oficina, de lunes a viernes de 08:00 a 18:00
8. Página de login y chat con el estilo de Cubo
9. Dockerfile y servicio `app` en Docker Compose

Y el deploy en AWS (EC2 + CloudFront), configurado desde la consola (sin PR necesaria)


## 3. Reglas de negocio adicionales por criterio

Tras leer las reglas de negocio establecidas, por criterio propio se agregaron algunas adicionales para darle más sentido al chatbot y mejorar la experiencia, las cuales son:
1. Capacidades máximas: se establecieron capacidades máximas para las salas (A a D = 7 y E = 10)
2. Capacidades mínimas: se necesita como mínimo un asistente
3. Reservas en el pasado: solo se pueden reservar salas en un tiempo futuro
4. Días y horarios de oficina: se establecen que los días y horarios son de lunes a viernes de 8:00 a 18:00.


## 4. El agente

### Cómo funciona

Se armó un grafo propio con LangGraph, con dos nodos: `agent` y `tools`. El mensaje del
usuario entra al nodo `agent`, que le pregunta al LLM qué hacer. Si el LLM pide una tool, el
grafo pasa por `tools`, ejecuta la función y vuelve a `agent` con el resultado. Ese ciclo se
repite hasta que el LLM responde con texto, y ahí termina.

Algunas decisiones del agente:

- El usuario no es un argumento de las tools: sale del token de login y llega por la
  configuración del grafo. El LLM nunca puede cancelar en nombre de otro.
- Cuando una tool falla, no devuelve un error, sino una descripción y una
  sugerencia de qué hacer.
- Los LLM a veces se equivocan calculando días de la semana, así que en cada turno el prompt
  recibe la fecha actual y un calendario dado en Python. Cuando el
  usuario dice "el jueves", el modelo copia la fecha del calendario en lugar de calcularla.
- La conversación se guarda en memoria para que el agente recuerde
  lo que se habló en los mensajes anteriores.
- El prompt está en un archivo YAML dividido en secciones con etiquetas XML y Markdown, para mejorar el formato del prompt.

### Las tools y sus flujos

Hay seis tools, una por cada cosa que el usuario puede querer hacer.

`list_available_rooms`: busca qué salas están libres en un horario. Recibe el inicio, el
fin y, si el usuario lo dijo, la cantidad de personas, para devolver solo las salas donde
entran.

`get_room_schedule`: muestra la agenda de una sala, con las franjas libres y ocupadas. Si
el usuario solo dice un día, se consulta el día completo de oficina. Las franjas seguidas se
agrupan (por ejemplo, "libre de 08:00 a 10:00") para que la respuesta sea corta y gaste menos
tokens.

`check_booking`: verifica si una reserva es posible sin guardar nada. Se usa apenas el
usuario dice sala y horario, antes de pedirle el título y los asistentes. Se agregó después
de probar la demo, porque una reserva de 4 horas recién se rechazaba al final, cuando el
usuario ya había dado todos los datos.

`create_booking`: crea la reserva. Necesita cinco datos: sala, inicio, fin, título y
cantidad de asistentes, y todos tienen que venir del usuario. Si falta alguno, el agente lo
pregunta. Con los cinco, muestra un resumen y espera la confirmación en otro mensaje. Las
reglas se vuelven a validar al crear, porque entre la verificación y la confirmación otro
usuario pudo haber ocupado la sala.

`list_my_bookings`: lista las reservas activas del usuario que todavía no terminaron. El
agente también la usa por su cuenta para encontrar una reserva antes de cancelarla.

`cancel_booking`: cancela una reserva propia. El agente primero busca la reserva con
`list_my_bookings`, pregunta cuál si hay varias, la muestra y espera el "sí". El usuario
nunca ve el id de la reserva: se identifica por sala, día y hora.

## 5. Desafíos principales

A continuación, se listan los principales desafíos y la resolución por la que se optó:

1. El LLM calculaba mal el día de la semana: En las pruebas el agente decía "lunes 18/10"
   cuando en realidad era domingo, y con eso una reserva podía quedar en el día equivocado. Se
   resolvió armando en Python un calendario de los próximos 14 días, con el día de la semana y
   la fecha, que se agrega al prompt en cada turno. Así el modelo copia la fecha en lugar de
   calcularla.

2. El agente inventaba datos: en una prueba creó una reserva con el título "?" sin haberle
   pedido el título al usuario y sin pedir confirmación. Se ajustó el prompt para que los cinco
   datos de la reserva (sala, inicio, fin, título y asistentes) los diga siempre el usuario, y
   para que el agente muestre un resumen y espere la confirmación en un mensaje aparte antes de
   crearla.

3. Tools mal llamadas: a veces el modelo intentaba llamar a una tool con un dato vacío, por
   ejemplo `title: null`. Groq rechazaba la llamada con un error `tool_use_failed` y el chat
   mostraba un mensaje de error. Ahora ese error se le devuelve al modelo con una indicación de
   que no use valores vacíos, y el modelo vuelve a intentar. En la mayoría de los casos termina
   preguntándole al usuario el dato que faltaba.

4. Errores que aparecían recién al final: si alguien pedía una sala por 4 horas, el agente
   le preguntaba el título y los asistentes, y recién al crear la reserva le avisaba que el
   máximo es de 3 horas. Se agregó la tool `check_booking`, que valida las reglas y la
   disponibilidad apenas hay sala y horario, sin guardar nada.

5. Límite de uso de Groq y demoras: con la cuenta gratuita de Groq hay un límite de tokens,
   y cada consulta de agenda gastaba unos 1500 tokens porque devolvía todos los slots de 30
   minutos. Se agruparon los slots seguidos en franjas, lo que bajó ese consumo un 94 %, y se
   redujo el razonamiento del modelo (`reasoning_effort="low"`) para que responda más rápido.
   Cuando igual se llega al límite, el chat muestra un mensaje propio en lugar de un error.

6. Los tests borraban los datos de prueba: los tests usaban la misma base de datos que las
   pruebas manuales, así que cada vez que se corrían se perdían las reservas cargadas a mano.
   Se creó una base de datos solo para los tests (`booking_test`).


## 6. Testing

A medida que se avanzó con el proyecto se construyeron diferentes test para comprobar la funcionalidad de:
- Las reglas de negocio
- Servicio de Postgres
- Hash, JWT vencido, login
- Agente de reservas, incluyendo sus tools, prompt, calendario y grafo
- Errores del /chat y /schedule como el 401, 422, 429, 503.

Se usó una base de datos solo para test separada, para no afectar la base de datos funcional.

El comportamiento se comprobó manualmente en local y en la demo desplegada, comprobando cada uno de los flujos de las tools del agente. Aunque al utilizar una API Key gratuita de Groq, solían ocurrir interrupciones debido al consumo máximo de tokens por ese día.


## 7. Deploy

Para desplegar el código se optó por AWS, debido a familiaridad. 
Se utilizó un EC2 con t3.micro con Docker Compose, de moto tal que se tiene la app y Postgres en la misma máquina.

Se recurrió a CloudFront debido a que se quiso evitar que la URL fuera solo HTTP y no HTTPS con certificado incluido y sin la necesidad de comprar un dominio.

En términos de seguirdad me conecté mediante SSH desde mi IP. Postgres no está expuesto y el .env está fuera de la imagen.


## 8. Limitaciones y mejoras futuras

Al tratarse de un challenge con tiempo y funcionalidades acotadas, se recurrió a una versión que cumpliera con los requerimientos, pero se puede seguir escalando. Algunas de posbibles mejoras son a las siguientes:

| Limitación | Mejora |
|---|---|
| La conversación se pierde si la app se reinicia (`MemorySaver` en RAM) | `PostgresSaver` |
| Cuota diaria del plan gratis de Groq | Plan pago de Groq u otro proveedor |
| Sin refresh token ni revocación del JWT | Refresh tokens |
| El alcance lo controla solo el prompt | Más nodos en la arquitectura agénica como el router, guardrails, convesacional, deny, etc. |
| Sin métrica de evaluación del agente | Se podrían hacer con Langsmith para comprobar el valor de la métrica del tool accuracy para diferentes escenarios |
