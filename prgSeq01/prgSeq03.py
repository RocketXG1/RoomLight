"""Secuencia FBI con PWM directo en GP16, relevador en GP17 y sensor en GP0.

El relevador se activa al terminar la rampa de encendido y se desactiva al
terminar la rampa de apagado. El PWM no esta invertido: 0 % es apagado y
100 % es encendido para una etapa de potencia activa en alto.
"""

import time
from machine import Pin
from lib.BlackLight.BlackLightControl import BlackLightControl


BLACK_LIGHT_PIN = 16
RELAY_PIN = 17
BLACK_LIGHT_FREQUENCY = 1000
SWITCH_PIN = 0

LIGHT_OFF_PERCENT = 0
LIGHT_ON_PERCENT = 100
RAMP_STEP_PERCENT = 1
RAMP_TIME_SECONDS = 1

WAKE_HOLD_SECONDS = 0.2
SLEEP_HOLD_SECONDS = 0.2
POLL_DELAY_SECONDS = 0.05

bSensor = Pin(SWITCH_PIN, Pin.IN)
bRelay = Pin(RELAY_PIN, Pin.OUT, value=0)
BlackLight = BlackLightControl(BLACK_LIGHT_PIN, BLACK_LIGHT_FREQUENCY)


def set_relay(active):
    """Controla el relevador activo en alto: True enciende y False apaga."""
    bRelay.value(1 if active else 0)


def _ticks_ms():
    """Regresa el contador de milisegundos compatible con MicroPython."""
    return time.ticks_ms()


def _elapsed_seconds(start_ticks):
    """Calcula segundos transcurridos usando ticks_diff para manejar overflow."""
    return time.ticks_diff(time.ticks_ms(), start_ticks) / 1000


def fbiWakeUp():
    """Sube el PWM de 0 a 100 % y despues activa el relevador."""
    BlackLight.ramp_percent(
        RAMP_STEP_PERCENT,
        RAMP_TIME_SECONDS,
        start_percent=LIGHT_OFF_PERCENT,
        end_percent=LIGHT_ON_PERCENT,
    )
    set_relay(True)


def fbiSleep():
    """Baja el PWM de 100 a 0 % y despues desactiva el relevador."""
    BlackLight.ramp_percent(
        RAMP_STEP_PERCENT,
        RAMP_TIME_SECONDS,
        start_percent=LIGHT_ON_PERCENT,
        end_percent=LIGHT_OFF_PERCENT,
    )
    set_relay(False)


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


def wait_for_low():
    """Espera a que el switch vuelva a bajo antes de aceptar otra cuenta."""
    while bSensor.value():
        time.sleep(POLL_DELAY_SECONDS)


def main():
    """Alterna encendido/apagado con activaciones del sensor en GP0."""
    light_is_on = False
    set_relay(False)
    BlackLight.set_percent(LIGHT_OFF_PERCENT)

    while True:
        if light_is_on:
            print("ON")
            wait_for_high_hold(SLEEP_HOLD_SECONDS)
            fbiSleep()
            light_is_on = False
            wait_for_low()
        else:
            print("OFF")
            wait_for_high_hold(WAKE_HOLD_SECONDS)
            fbiWakeUp()
            light_is_on = True
            wait_for_low()


def shutdown():
    """Apaga ambas salidas y libera el PWM, incluso si un apagado falla."""
    try:
        set_relay(False)
    finally:
        try:
            BlackLight.set_percent(LIGHT_OFF_PERCENT)
        finally:
            BlackLight.deinit()


def run():
    """Ejecuta main y apaga las salidas ante una interrupcion o un error."""
    try:
        main()
    finally:
        shutdown()


if __name__ == "__main__":
    run()
