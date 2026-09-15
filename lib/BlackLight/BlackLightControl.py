from machine import Pin, PWM
import time


class BlackLightControl:
    def __init__(self, pin, frequency=1000):
        self._pwm = PWM(Pin(pin))
        self._pwm.freq(frequency)
        self._percent = 0
        self.set_percent(0)

    def set_percent(self, percent):
        percent = max(0, min(100, int(percent)))
        self._percent = percent
        duty = int((percent / 100) * 65535)
        self._pwm.duty_u16(duty)

    def ramp_percent(self, step_percent, total_time_s, start_percent=0, end_percent=100):
        step_percent = abs(int(step_percent))
        if step_percent < 1:
            step_percent = 1
        start_percent = max(0, min(100, int(start_percent)))
        end_percent = max(0, min(100, int(end_percent)))

        if start_percent == end_percent:
            self.set_percent(end_percent)
            return

        direction = 1 if end_percent > start_percent else -1
        step_percent *= direction

        steps = int((end_percent - start_percent) / step_percent)
        if steps == 0:
            self.set_percent(end_percent)
            return

        delay_s = total_time_s / abs(steps)
        current = start_percent
        for _ in range(abs(steps)):
            self.set_percent(current)
            time.sleep(delay_s)
            current += step_percent

        self.set_percent(end_percent)

    def get_percent(self):
        """Regresa el ultimo porcentaje aplicado a la salida PWM.

        Este metodo permite que una secuencia consulte el punto real de una
        transicion sin acceder directamente al atributo privado ``_percent``.
        """
        return self._percent

    def start_ramp(self, end_percent, step_percent=1, step_interval_ms=20):
        """Inicia o redirige una rampa no bloqueante desde el PWM actual.

        ``end_percent`` es el nuevo objetivo, ``step_percent`` es el cambio por
        paso y ``step_interval_ms`` indica cada cuantos milisegundos puede
        ejecutarse un paso. La funcion solo configura la transicion; se debe
        llamar periodicamente a :meth:`update_ramp` desde el ciclo principal.

        Volver a llamar este metodo durante una rampa conserva el porcentaje
        actual y permite invertir inmediatamente la direccion hacia otro
        objetivo, sin saltar primero a uno de los extremos.
        """
        self._ramp_target = max(0, min(100, int(end_percent)))
        self._ramp_step = max(1, abs(int(step_percent)))
        self._ramp_interval_ms = max(1, int(step_interval_ms))
        self._ramp_last_step = time.ticks_ms()
        self._ramp_active = self._percent != self._ramp_target

    def update_ramp(self, now_ms=None):
        """Avanza como maximo un paso de la rampa y regresa inmediatamente.

        Debe llamarse repetidamente desde una secuencia no bloqueante. Regresa
        ``True`` si aplico un nuevo porcentaje y ``False`` si la rampa termino
        o aun no ha transcurrido el intervalo configurado.
        """
        if not getattr(self, "_ramp_active", False):
            return False

        if now_ms is None:
            now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, self._ramp_last_step) < self._ramp_interval_ms:
            return False

        if self._percent < self._ramp_target:
            next_percent = min(
                self._percent + self._ramp_step, self._ramp_target
            )
        else:
            next_percent = max(
                self._percent - self._ramp_step, self._ramp_target
            )

        self.set_percent(next_percent)
        self._ramp_last_step = now_ms
        self._ramp_active = self._percent != self._ramp_target
        return True

    def is_ramping(self):
        """Indica si una rampa no bloqueante aun no alcanza su objetivo."""
        return getattr(self, "_ramp_active", False)

    def get_ramp_target(self):
        """Regresa el objetivo vigente de la rampa no bloqueante."""
        return getattr(self, "_ramp_target", self._percent)

    def deinit(self):
        self._pwm.deinit()
