from django.dispatch import Signal

# Sent after meals change. Receivers get `household` and `dates` (an iterable of dates).
meals_changed = Signal()
