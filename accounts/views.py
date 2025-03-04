# accounts/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError

from .models import Account, AccountType, AccountStatusHistory
from .forms import AccountForm, AccountStatusActionForm, AccountTypeForm, AccountSearchForm

@login_required
def account_list(request):
    """Display a list of all accounts with filtering options."""
    # Get filter parameters directly from request.GET
    status_filter = request.GET.get('status', '')
    account_type_filter = request.GET.get('account_type', '')
    search_query = request.GET.get('search', '')
    
    # Start with all accounts
    accounts = Account.objects.all()
    
    # Apply filters if provided
    if status_filter:
        accounts = accounts.filter(status=status_filter)
    
    if account_type_filter:
        accounts = accounts.filter(account_type_id=account_type_filter)
    
    if search_query:
        accounts = accounts.filter(
            Q(number__icontains=search_query) |
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    # Order accounts by number
    accounts = accounts.order_by('number')
    
    # Pagination - this was missing
    paginator = Paginator(accounts, 50)  # Show 50 accounts per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'page_obj': page_obj,  # Now page_obj is defined
        'account_types': AccountType.objects.all().order_by('name'),
        'status_choices': Account.STATUS_CHOICES,
    }
    
    return render(request, 'accounts/account_list.html', context)

@login_required
def account_create(request):
    """Handle creation of a new account."""
    if request.method == 'POST':
        form = AccountForm(request.POST)
        if form.is_valid():
            account = form.save()
            messages.success(
                request,
                f'Account {account.number} - {account.name} has been created successfully.'
            )
            return redirect('/accounts/' + account.number)
    else:
        form = AccountForm()
    
    context = {
        'form': form,
        'account_types': AccountType.objects.all().order_by('name'),
    }
    
    return render(request, 'accounts/account_form.html', context)

@login_required
def account_edit(request, number):
    """Handle editing of an existing account."""
    account = get_object_or_404(Account, number=number)
    
    if request.method == 'POST':
        form = AccountForm(request.POST, instance=account)
        if form.is_valid():
            account = form.save()
            messages.success(
                request,
                f'Account {account.number} - {account.name} has been updated successfully.'
            )
            return redirect('/accounts/' + account.number)
    else:
        form = AccountForm(instance=account)
    
    context = {
        'form': form,
        'account': account,
    }
    
    return render(request, 'accounts/account_form.html', context)

@login_required
def account_status_change(request, number):
    """Handle account status workflow actions like requests, approvals, and rejections."""
    account = get_object_or_404(Account, number=number)
    
    if request.method == 'POST':
        form = AccountStatusActionForm(request.POST, account=account, user=request.user)
        if form.is_valid():
            action = form.cleaned_data['action']
            reason = form.cleaned_data['reason']
            
            # Get the user's email or username for tracking
            user_identifier = request.user.email if request.user.email else request.user.username
            
            try:
                # Execute the appropriate action based on the form selection
                success = False
                
                # Request actions (regular users)
                if action == 'request_archival':
                    success = account.request_archival(reason=reason, requested_by=user_identifier)
                    message = "Archival request has been submitted successfully."
                elif action == 'request_unarchival':
                    success = account.request_unarchival(reason=reason, requested_by=user_identifier)
                    message = "Unarchival request has been submitted successfully."
                
                # Approval actions (for authorized users)
                elif action == 'approve_creation':
                    success = account.approve_creation(reason=reason, approved_by=user_identifier)
                    message = "Account has been approved and activated."
                elif action == 'reject_creation':
                    success = account.reject_creation(reason=reason, approved_by=user_identifier)
                    message = "Account has been rejected and removed."
                    # Handle special case of deletion - redirect to list view
                    messages.success(request, message)
                    return redirect('accounts:account_list')
                elif action == 'approve_archival':
                    success = account.approve_archival(reason=reason, approved_by=user_identifier)
                    message = "Archival request has been approved."
                elif action == 'reject_archival':
                    success = account.reject_archival(reason=reason, approved_by=user_identifier)
                    message = "Archival request has been rejected."
                elif action == 'approve_unarchival':
                    success = account.approve_unarchival(reason=reason, approved_by=user_identifier)
                    message = "Unarchival request has been approved."
                elif action == 'reject_unarchival':
                    success = account.reject_unarchival(reason=reason, approved_by=user_identifier)
                    message = "Unarchival request has been rejected."
                
                # Direct actions (admin only)
                elif action == 'activate':
                    success = account.activate(reason=reason, approved_by=user_identifier)
                    message = "Account has been directly activated."
                elif action == 'archive':
                    success = account.archive(reason=reason, approved_by=user_identifier)
                    message = "Account has been directly archived."
                elif action == 'unarchive':
                    success = account.unarchive(reason=reason, approved_by=user_identifier)
                    message = "Account has been directly unarchived."
                
                if success:
                    messages.success(request, message)
                else:
                    messages.warning(request, "No changes were made to the account status.")
                
            except ValidationError as e:
                messages.error(request, f"Error: {str(e)}")
            
            return redirect('accounts:account_detail', number=account.number)
    else:
        form = AccountStatusActionForm(account=account, user=request.user)
    
    context = {
        'form': form,
        'account': account,
        'title': 'Account Status Action',
    }
    
    return render(request, 'accounts/account_status_form.html', context)

@login_required
def account_detail(request, number):
    """Display detailed information about a specific account."""
    account = get_object_or_404(Account, number=number)
    
    context = {
        'account': account,
        'status_history': account.status_history.all().order_by('-effective_date'),
        'child_accounts': account.children.all().order_by('number'),
    }
    
    return render(request, 'accounts/account_detail.html', context)

@login_required
def account_type_list(request):
    """Display a list of all account types."""
    account_types = AccountType.objects.all().order_by('name')
    
    context = {
        'account_types': account_types,
    }
    
    return render(request, 'accounts/account_type_list.html', context)

@login_required
def request_archival(request, number):
    """Shortcut to request archival for an account."""
    account = get_object_or_404(Account, number=number)
    if account.status != Account.STATUS_ACTIVE:
        messages.error(request, "Only active accounts can be requested for archival.")
        return redirect('accounts:account_detail', number=account.number)
    
    # Pre-select the action and redirect to the status change form
    initial_data = {'action': 'request_archival'}
    return redirect_with_initial(request, 'accounts:account_status_change', 
                                initial_data, number=account.number)

@login_required
def request_unarchival(request, number):
    """Shortcut to request unarchival for an account."""
    account = get_object_or_404(Account, number=number)
    if account.status != Account.STATUS_ARCHIVED:
        messages.error(request, "Only archived accounts can be requested for unarchival.")
        return redirect('accounts:account_detail', number=account.number)
    
    initial_data = {'action': 'request_unarchival'}
    return redirect_with_initial(request, 'accounts:account_status_change', 
                                initial_data, number=account.number)

# Helper function for redirecting with initial form data
def redirect_with_initial(request, view_name, initial_data, **kwargs):
    """Save initial form data to session and redirect to a view."""
    request.session['form_initial'] = initial_data
    return redirect(view_name, **kwargs)
