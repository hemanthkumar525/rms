// In static/js/notifications.js

document.addEventListener("DOMContentLoaded", function() {
    function fetchNotifications() {
        fetch('/notifications/')
            .then(response => response.json())
            .then(data => {
                const notificationList = document.getElementById('notification-list');
                notificationList.innerHTML = '';

                data.notifications.forEach(notification => {
                    const li = document.createElement('li');
                    li.innerHTML = `${notification.message} <small>${notification.timestamp}</small>`;
                    if (!notification.is_read) {
                        const markAsReadLink = document.createElement('a');
                        markAsReadLink.href = `/notifications/mark-as-read/${notification.id}/`;
                        markAsReadLink.innerText = 'Mark as Read';
                        li.appendChild(markAsReadLink);
                    }
                    notificationList.appendChild(li);
                });
            });
    }

    fetchNotifications();
});