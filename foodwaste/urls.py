from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from inventory import views
from inventory import ngo_views

router = DefaultRouter()
router.register('inventory', views.InventoryViewSet, basename='inventory')
router.register('products', views.ProductViewSet, basename='products')
router.register('categories', views.CategoryViewSet)
router.register('alerts', views.AlertViewSet, basename='alerts')
router.register('transactions', views.TransactionViewSet, basename='transactions')
router.register('donations', views.DonationViewSet, basename='donations')
router.register('demand', views.DemandViewSet, basename='demand')
router.register('predictions', views.PredictionViewSet, basename='predictions')

urlpatterns = [
    path('', views.landing, name='landing'),
    path('app/', views.dashboard, name='dashboard'),
    path('login/', ngo_views.RoleLoginView.as_view(), name='login'),
    path('login/ngo/', ngo_views.RoleLoginView.as_view(role='ngo'), name='ngo_login'),
    path('signup/', views.signup, name='signup'),
    path('signup/ngo/', ngo_views.ngo_signup, name='ngo_signup'),
    path('surplus/', ngo_views.business_surplus, name='business_surplus'),
    path('surplus/<int:pk>/cancel/', ngo_views.cancel_offer, name='cancel_surplus_offer'),
    path('surplus/<int:pk>/approve/', ngo_views.approve_request, name='approve_surplus_request'),
    path('ngo/', ngo_views.ngo_dashboard, name='ngo_dashboard'),
    path('ngo/offers/', ngo_views.ngo_dashboard, {'section': 'offers'}, name='ngo_offers'),
    path('ngo/requests/', ngo_views.ngo_dashboard, {'section': 'requests'}, name='ngo_requests'),
    path('ngo/pickups/', ngo_views.ngo_dashboard, {'section': 'pickups'}, name='ngo_pickups'),
    path('ngo/impact/', ngo_views.ngo_dashboard, {'section': 'impact'}, name='ngo_impact'),
    path('ngo/offers/<int:pk>/request/', ngo_views.request_offer, name='ngo_request_offer'),
    path('ngo/offers/<int:pk>/pickup/', ngo_views.confirm_pickup, name='ngo_confirm_pickup'),
    path('ngo/offers/<int:pk>/delivered/', ngo_views.confirm_delivery, name='ngo_confirm_delivery'),
    path('notifications/', ngo_views.notifications_page, name='notifications'),
    path('notifications/<int:pk>/read/', ngo_views.read_notification, name='read_notification'),
    path('notifications/read-all/', ngo_views.read_all_notifications, name='read_all_notifications'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('admin/', admin.site.urls),
    path('api/summary/', views.summary),
    path('api/business/', views.business_settings),
    path('api/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls')),
]
