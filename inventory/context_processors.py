from .models import Notification


def notification_count(request):
    if not request.user.is_authenticated:
        return {'notification_unread_count': 0}
    return {'notification_unread_count': Notification.objects.filter(
        recipient=request.user, read_at__isnull=True).count()}
