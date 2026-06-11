"""Secuencia de control FBI para la luz negra.

La secuencia escucha el GPIO 27 como switch y controla la luz negra
con la clase BlackLightControl. El control de porcentaje está invertido:
100 % apaga la luz y 50 % representa la luz encendida.
"""

import time
from machine import Pin
from lib.BlackLight.BlackLightControl import BlackLightControl


BLACK_LIGHT_PIN = 28
BLACK_LIGHT_FREQUENCY = 1000
SWITCH_PIN = 27

LIGHT_OFF_PERCENT = 100
LIGHT_ON_PERCENT = 50
RAMP_STEP_PERCENT = 1
RAMP_TIME_SECONDS = 0.5

WAKE_HOLD_SECONDS = 2
SLEEP_HOLD_SECONDS = 3
POLL_DELAY_SECONDS = 0.05


bSensor = Pin(SWITCH_PIN, Pin.IN)
BlackLight = BlackLightControl(BLACK_LIGHT_PIN, BLACK_LIGHT_FREQUENCY)


def _ticks_ms():
    """Regresa el contador de milisegundos compatible con MicroPython."""
    return time.ticks_ms()


def _elapsed_seconds(start_ticks):
    """Calcula segundos transcurridos usando ticks_diff para manejar overflow."""
    return time.ticks_diff(time.ticks_ms(), start_ticks) / 1000


def fbiWakeUp():
    """Enciende la luz con rampa de 50 % a 100 %."""
    BlackLight.ramp_percent(
        RAMP_STEP_PERCENT,
        RAMP_TIME_SECONDS,
        start_percent=LIGHT_ON_PERCENT,
        end_percent=LIGHT_OFF_PERCENT,
    )


def fbiSleep():
    """Apaga la luz con rampa de 100 % a 50 %."""
    BlackLight.ramp_percent(
        RAMP_STEP_PERCENT,
        RAMP_TIME_SECONDS,
        start_percent=LIGHT_OFF_PERCENT,
        end_percent=LIGHT_ON_PERCENT,
    )


def wait_for_high_hold(hold_seconds):
    """Espera hasta que el switch permanezca en alto el tiempo indicado."""
    high_started_at = None

    while True:
        if bSensor.value():
            if high_started_at is None:
                high_started_at = _ticks_ms()
            elif _elapsed_seconds(high_started_at) >= hold_seconds:
                return
        else:
            high_started_at = None

        time.sleep(POLL_DELAY_SECONDS)


def main():
    """Ejecuta la secuencia alternando entre WakeUp y Sleep por GPIO 27."""
    light_is_on = False
    BlackLight.set_percent(LIGHT_OFF_PERCENT)

    while True:
        if light_is_on:
            wait_for_high_hold(SLEEP_HOLD_SECONDS)
            fbiSleep()
            light_is_on = False
        else:
            wait_for_high_hold(WAKE_HOLD_SECONDS)
            fbiWakeUp()
            light_is_on = True


if __name__ == "__main__":
    try:
        main()
    finally:
        BlackLight.deinit()
