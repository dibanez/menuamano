import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from reminders import push, services

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send the reminders that are due. With --loop, keep doing it every N seconds."

    def add_arguments(self, parser):
        parser.add_argument("--loop", type=int, default=0, help="Repeat every N seconds (0 = run once).")

    def handle(self, *args, loop, **options):
        if not push.configured():
            logger.warning("reminders are off: set VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY")
        while True:
            if push.configured():
                delivered = services.send_due()
                if delivered:
                    logger.info("reminders delivered: %s", delivered)
            close_old_connections()
            if loop <= 0:
                return
            time.sleep(loop)
