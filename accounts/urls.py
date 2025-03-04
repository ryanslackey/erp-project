# accounts/urls.py
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # List view
    path('', views.account_list, name='account_list'),
    
    # Create view
    path('create/', views.account_create, name='account_create'),
    
    # Account Types list - make sure this is included
    path('types/', views.account_type_list, name='account_type_list'),
    
    # Detail view
    path('<str:number>/', views.account_detail, name='account_detail'),
    
    # Edit view
    path('<str:number>/edit/', views.account_edit, name='account_edit'),
    
    # Status change view
    path('<str:number>/status/', views.account_status_change, name='account_status_change'),
]

