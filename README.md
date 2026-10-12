# Backend notifications

Order, refund, wishlist-restock, low-stock, and product-approval events are stored
as in-app notifications and also sent through Django's configured email backend.
In-app notifications are available at `/api/notifications/`; authenticated users
can mark individual notifications or all notifications as read.

For local development, the console email backend is used by default, so messages
appear in the Django server output. Configure SMTP delivery with these `.env`
values:

```text
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-smtp-user
EMAIL_HOST_PASSWORD=your-smtp-password
EMAIL_USE_TLS=true
EMAIL_USE_SSL=false
DEFAULT_FROM_EMAIL=CraftGenius <notifications@example.com>
FRONTEND_URL=https://your-frontend.example.com
```

Low-stock alerts are sent when inventory falls to five units or fewer, is
restocked at five units or fewer, or sells out. Wishlist restock alerts are
sent when an active, approved product changes from zero (or less) to a positive
quantity.
