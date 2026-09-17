"""Secuencia de luz negra activada por un sensor de movimiento.

El sensor se atiende por interrupcion y las rampas PWM son cooperativas: cada
iteracion avanza como maximo un paso. Una deteccion durante el apagado cambia
el objetivo a encendido desde el porcentaje actual, sin saltos en la salida.

La electronica es inversa: 100 % apaga la salida y 50 % la enciende.
"""

import time
from machine import Pin
from lib.Neopixel.neopixel import Neopixel
from lib.BlackLight.BlackLightControl import BlackLightControl


# GPIO que entrega la señal PWM al controlador de la luz negra.
BLACK_LIGHT_PIN = 28
# Frecuencia, en hercios, utilizada por la salida PWM.
BLACK_LIGHT_FREQUENCY = 1000
# GPIO de entrada conectado a la salida digital del sensor de movimiento.
MOTION_SENSOR_PIN = 27

# Porcentaje PWM que apaga la luz debido a la electronica inversa.
LIGHT_OFF_PERCENT = 100
# Porcentaje PWM que enciende la luz al nivel de trabajo deseado.
LIGHT_ON_PERCENT = 50
# Cambio porcentual aplicado en cada paso de una rampa.
RAMP_STEP_PERCENT = 1
# Duracion nominal, en segundos, de una rampa completa entre ON y OFF.
RAMP_TIME_SECONDS = 1

# Segundos que la salida permanece en ON; cada deteccion reinicia la cuenta.
ON_HOLD_SECONDS = 30
# Pausa corta entre iteraciones para limitar uso de CPU sin perder respuesta.
LOOP_DELAY_SECONDS = 0.005

# GPIO utilizado por el NeoPixel que informa el estado de la secuencia.
READY_PIN = 16
# Maquina de estados PIO reservada para controlar el NeoPixel.
READY_STATE_MACHINE = 1
# Brillo global aplicado al NeoPixel indicador.
READY_BRIGHTNESS = 10

# Color del NeoPixel durante la inicializacion del sistema.
COLOR_READY = (0, 255, 255)
# Color del NeoPixel cuando la salida se encuentra apagada.
COLOR_OFF = (255, 0, 0)
# Color del NeoPixel durante la rampa hacia encendido.
COLOR_WAKING = (255, 150, 0)
# Color del NeoPixel cuando la salida esta encendida y temporizada.
COLOR_ON = (0, 255, 0)
# Color del NeoPixel durante la rampa hacia apagado.
COLOR_SLEEPING = (200, 0, 100)

# Identificador del estado con la salida completamente apagada.
STATE_OFF = 0
# Identificador del estado de rampa hacia el nivel encendido.
STATE_WAKING = 1
# Identificador del estado encendido con temporizador de permanencia.
STATE_ON_HOLD = 2
# Identificador del estado de rampa hacia el nivel apagado.
STATE_SLEEPING = 3


# Entrada digital utilizada para leer e interrumpir por cambios del sensor.
bSensor = Pin(MOTION_SENSOR_PIN, Pin.IN)
# Controlador encargado de aplicar porcentajes y rampas a la salida PWM.
BlackLight = BlackLightControl(BLACK_LIGHT_PIN, BLACK_LIGHT_FREQUENCY)
# NeoPixel de un LED utilizado como indicador visual del estado actual.
Ready = Neopixel(1, READY_STATE_MACHINE, READY_PIN, "GRB")

# Ultimo nivel logico informado por el sensor; se actualiza desde el IRQ.
_sensor_active = bool(bSensor.value())
# Contador circular de 8 bits para registrar flancos ascendentes del sensor.
_motion_sequence = 0


def _ticks_ms():
    """Regresa el contador monotono de milisegundos de MicroPython."""
    return time.ticks_ms()


def _seconds_to_ms(seconds):
    """Convierte segundos configurables a milisegundos enteros."""
    return max(0, int(seconds * 1000))


def _deadline_reached(now_ms, deadline_ms):
    """Compara una fecha limite de ticks contemplando su overflow."""
    return time.ticks_diff(now_ms, deadline_ms) >= 0


def _sensor_irq(pin):
    """Registra cambios del sensor con el minimo trabajo dentro del IRQ.

    Un flanco ascendente incrementa el contador circular ``_motion_sequence``
    para que main() no pierda una deteccion aunque el sensor vuelva a bajo.
    Ambos flancos actualizan ``_sensor_active``. El trabajo de PWM se difiere al
    ciclo principal para mantener esta interrupcion corta y no bloqueante.
    """
    global _sensor_active, _motion_sequence

    # Nivel del sensor capturado en el instante en que ocurrio el flanco.
    active = bool(pin.value())
    _sensor_active = active
    if active:
        _motion_sequence = (_motion_sequence + 1) & 0xFF


def _ramp_interval_ms():
    """Calcula el intervalo que conserva la duracion nominal de la rampa."""
    # Distancia porcentual total entre los niveles fisicos ON y OFF.
    distance = abs(LIGHT_OFF_PERCENT - LIGHT_ON_PERCENT)
    # Cantidad de pasos necesarios, redondeada hacia arriba.
    steps = max(1, (distance + RAMP_STEP_PERCENT - 1) // RAMP_STEP_PERCENT)
    return max(1, _seconds_to_ms(RAMP_TIME_SECONDS) // steps)


def fbiWakeUp():
    """Solicita una rampa no bloqueante desde el PWM actual hacia ON.

    A diferencia de la funcion de prgSeq01, esta funcion no espera a completar
    la rampa. ``main()`` debe llamar periodicamente a ``update_ramp()``.
    """
    BlackLight.start_ramp(
        LIGHT_ON_PERCENT, RAMP_STEP_PERCENT, _ramp_interval_ms()
    )


def fbiSleep():
    """Solicita una rampa no bloqueante desde el PWM actual hacia OFF.

    Una llamada posterior a ``fbiWakeUp()`` redirige la misma transicion desde
    el porcentaje alcanzado, por lo que una deteccion interrumpe el apagado sin
    producir un salto en el PWM.
    """
    BlackLight.start_ramp(
        LIGHT_OFF_PERCENT, RAMP_STEP_PERCENT, _ramp_interval_ms()
    )


def _show_state(state):
    """Actualiza el NeoPixel solamente cuando cambia el estado de secuencia."""
    # Tabla que relaciona cada identificador de estado con su color indicador.
    colors = (
        COLOR_OFF,
        COLOR_WAKING,
        COLOR_ON,
        COLOR_SLEEPING,
    )
    Ready.fill(colors[state])
    Ready.show()


def main():
    """Ejecuta el control por estados, temporizado y sin esperas bloqueantes."""
    global _sensor_active

    # Estado logico inicial de la maquina de estados.
    state = STATE_OFF
    # Ultimo estado mostrado; evita actualizar el NeoPixel innecesariamente.
    displayed_state = None
    # Ultima deteccion procesada por main; permite reconocer una nueva.
    processed_motion_sequence = _motion_sequence
    # Tick futuro hasta el que debe mantenerse la salida encendida.
    on_deadline = None
    # Tiempo de permanencia convertido una sola vez a milisegundos.
    hold_ms = _seconds_to_ms(ON_HOLD_SECONDS)

    BlackLight.set_percent(LIGHT_OFF_PERCENT)
    Ready.brightness(READY_BRIGHTNESS)
    Ready.fill(COLOR_READY)
    Ready.show()

    # Referencia al IRQ que escucha los flancos de activacion y desactivacion.
    sensor_irq = bSensor.irq(
        trigger=Pin.IRQ_RISING | Pin.IRQ_FALLING,
        handler=_sensor_irq,
    )

    try:
        # Si el sensor ya estaba activo antes de instalar el IRQ, se procesa
        # como una deteccion inicial aunque no exista un nuevo flanco.
        if _sensor_active:
            fbiWakeUp()
            state = STATE_WAKING

        while True:
            # Tick comun de esta iteracion para rampas y temporizadores.
            now_ms = _ticks_ms()
            # Indica si el IRQ registro una deteccion aun no procesada.
            motion_detected = processed_motion_sequence != _motion_sequence
            if motion_detected:
                processed_motion_sequence = _motion_sequence

                if state == STATE_ON_HOLD:
                    on_deadline = time.ticks_add(now_ms, hold_ms)
                elif state != STATE_WAKING:
                    fbiWakeUp()
                    state = STATE_WAKING
                    on_deadline = None

            BlackLight.update_ramp(now_ms)

            if state == STATE_WAKING:
                if BlackLight.get_percent() == LIGHT_ON_PERCENT:
                    state = STATE_ON_HOLD
                    on_deadline = time.ticks_add(now_ms, hold_ms)

            elif state == STATE_ON_HOLD:
                if on_deadline is not None and _deadline_reached(
                    now_ms, on_deadline
                ):
                    if _sensor_active:
                        # Un PIR puede permanecer alto sin producir nuevos
                        # flancos; en ese caso no se apaga una salida ocupada.
                        on_deadline = time.ticks_add(now_ms, hold_ms)
                    else:
                        fbiSleep()
                        state = STATE_SLEEPING
                        on_deadline = None

            elif state == STATE_SLEEPING:
                if BlackLight.get_percent() == LIGHT_OFF_PERCENT:
                    state = STATE_OFF

            if state != displayed_state:
                _show_state(state)
                displayed_state = state

            time.sleep(LOOP_DELAY_SECONDS)
    finally:
        sensor_irq = None
        bSensor.irq(handler=None)


if __name__ == "__main__":
    try:
        main()
    finally:
        BlackLight.deinit()
