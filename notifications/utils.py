from .models import Notification
from django.contrib.contenttypes.models import ContentType

def create_notification(recipient, notification_type, title, message, related_object=None):
    """
    Utility function to create notifications consistently across the project
    """
    notification = Notification.objects.create(
        recipient=recipient,
        notification_type=notification_type,
        title=title,
        message=message
    )
    
    if related_object:
        notification.content_type = ContentType.objects.get_for_model(related_object)
        notification.object_id = related_object.id
        notification.save()
    
    return notification