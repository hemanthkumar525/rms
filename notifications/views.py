from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from .models import Notification

# Create your views here.

@login_required
def notification_list(request):
    """View for listing all notifications with pagination"""
    try:
        # Create a test notification if none exist
        if not Notification.objects.filter(recipient=request.user).exists():
            Notification.objects.create(
                recipient=request.user,
                notification_type='system',
                title='Welcome to RMS',
                message='Welcome to the Rental Management System. This is a test notification.'
            )
        
        notifications_list = Notification.objects.filter(recipient=request.user).order_by('-created_at')
        paginator = Paginator(notifications_list, 10)  # Show 10 notifications per page
        
        page = request.GET.get('page')
        notifications = paginator.get_page(page)
        
        context = {
            'notifications': notifications,
            'total_count': notifications_list.count(),
            'unread_count': notifications_list.filter(is_read=False).count()
        }
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse(context)
            
        return render(request, 'notifications/notification_list.html', context)
        
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': str(e)}, status=500)
        messages.error(request, f'Error loading notifications: {str(e)}')
        return render(request, 'notifications/notification_list.html', {'error': str(e)})

@login_required
def get_notifications_ajax(request):
    """Get notifications for AJAX requests"""
    try:
        notifications = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).order_by('-created_at')[:5]
        
        notifications_data = [{
            'id': notification.id,
            'title': notification.title,
            'message': notification.message,
            'type': notification.get_notification_type_display(),
            'created_at': notification.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'is_read': notification.is_read,
        } for notification in notifications]
        
        unread_count = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()
        
        return JsonResponse({
            'notifications': notifications_data,
            'unread_count': unread_count
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def mark_as_read(request, pk):
    """Mark a specific notification as read"""
    try:
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
        notification.is_read = True
        notification.save()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success'})
        
        messages.success(request, 'Notification marked as read.')
        return redirect('notifications:notification_list')
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': str(e)}, status=500)
        messages.error(request, f'Error marking notification as read: {str(e)}')
        return redirect('notifications:notification_list')

@login_required
def mark_all_read(request):
    """Mark all notifications as read for the current user"""
    try:
        Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'status': 'success'})
        
        messages.success(request, 'All notifications marked as read.')
        return redirect('notifications:notification_list')
    except Exception as e:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'error': str(e)}, status=500)
        messages.error(request, f'Error marking all notifications as read: {str(e)}')
        return redirect('notifications:notification_list')
