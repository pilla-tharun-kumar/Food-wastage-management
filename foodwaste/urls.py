from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from inventory import views

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
    path('', views.dashboard, name='dashboard'),
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('signup/', views.signup, name='signup'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('admin/', admin.site.urls),
    path('api/summary/', views.summary),
    path('api/business/', views.business_settings),
    path('api/', include(router.urls)),
    path('api-auth/', include('rest_framework.urls')),
]
