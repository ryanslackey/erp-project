# accounts/forms.py
from django import forms
from django.core.exceptions import ValidationError
from .models import Account, AccountType, AccountStatusHistory
from .validators import validate_account_number_range

class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = ['number', 'name', 'account_type', 'description', 'parent']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'number': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
        }
        help_texts = {
            'number': 'Enter a 6-digit account number that falls within the range for the selected account type.',
            'parent': 'Optionally select a parent account if this is a sub-account.',
        }
    
    def __init__(self, *args, **kwargs):
        """
        Initialize the form with custom field configurations.
        """
        super().__init__(*args, **kwargs)
        
        # Add Bootstrap classes to all fields
        for field_name, field in self.fields.items():
            if 'class' not in field.widget.attrs:
                field.widget.attrs['class'] = 'form-control'
        
        # Set up the account type field to show account types in a dropdown
        self.fields['account_type'].widget = forms.Select(attrs={
            'class': 'form-select',
        })
        
        # Set up the parent account field to show account numbers and names
        self.fields['parent'].queryset = Account.objects.filter(is_active=True)
        self.fields['parent'].label_from_instance = lambda obj: f"{obj.number} - {obj.name}"
        self.fields['parent'].widget = forms.Select(attrs={
            'class': 'form-select',
        })
        # If this is a new account being created, it will automatically
        # be assigned PENDING_APPROVAL status, so we might want to inform the user
        if not self.instance.pk:
            self.fields['number'].help_text += ' Note: New accounts require approval before becoming active.'
    def clean_number(self):
        """
        Basic validation for the account number field.
        """
        number = self.cleaned_data.get('number')
        
        # If we're editing an existing account, and the number hasn't changed,
        # skip the uniqueness check because we know it's already valid
        if self.instance.pk and self.instance.number == number:
            return number
        
        # Check if the account number already exists
        if Account.objects.filter(number=number).exists():
            raise ValidationError('An account with this number already exists.')
        
        return number
    
    def clean(self):
        """
        Perform validation across multiple fields.
        """
        cleaned_data = super().clean()
        
        # Get the values from cleaned_data
        number = cleaned_data.get('number')
        account_type = cleaned_data.get('account_type')
        
        # Only validate if we have both number and account_type
        if number and account_type:
            try:
                # Validate the account number range
                from .validators import validate_account_number_range
                validate_account_number_range(number, account_type)
            except ValidationError as e:
                # Add the error to the number field
                self.add_error('number', str(e))
        
        # Parent-child validation
        parent = cleaned_data.get('parent')
        
        # Prevent an account from being its own parent
        if self.instance.pk and parent and parent.pk == self.instance.pk:
            self.add_error('parent', 'An account cannot be its own parent.')
        
        # Ensure parent and child accounts have the same account type
        if parent and account_type and parent.account_type != account_type:
            self.add_error('parent', 
                'Parent and child accounts must have the same account type. '
                f'This account is {account_type.name}, but the parent is {parent.account_type.name}.'
            )
        
        # Prevent circular references in the parent-child hierarchy
        if parent and self.instance.pk:
            # Get all descendants of the current account
            descendants = self._get_descendants(self.instance)
            if parent.pk in [d.pk for d in descendants]:
                self.add_error('parent', 
                    'This would create a circular reference in the account hierarchy. '
                    'An account cannot have one of its descendants as its parent.'
                )
        
        return cleaned_data
    
    def _get_descendants(self, account):
        """
        Helper method to get all descendants of an account.
        """
        descendants = []
        children = account.children.all()
        
        for child in children:
            descendants.append(child)
            descendants.extend(self._get_descendants(child))
        
        return descendants



class AccountStatusActionForm(forms.Form):
    """
    Form for requesting or approving account status changes.
    
    This form handles the various workflow actions like requesting archival,
    approving creation, rejecting unarchival, etc. It dynamically shows only
    the actions that are valid for the current account status and user permissions.
    """
    ACTION_CHOICES = [
        # Request actions (by regular users)
        ('request_archival', 'Request Account Archival'),
        ('request_unarchival', 'Request Account Unarchival'),
        
        # Approval actions (by authorized approvers)
        ('approve_creation', 'Approve Account Creation'),
        ('reject_creation', 'Reject Account Creation'),
        ('approve_archival', 'Approve Archival Request'),
        ('reject_archival', 'Reject Archival Request'),
        ('approve_unarchival', 'Approve Unarchival Request'),
        ('reject_unarchival', 'Reject Unarchival Request'),
        
        # Direct actions (admin only)
        ('activate', 'Directly Activate Account'),
        ('archive', 'Directly Archive Account'),
        ('unarchive', 'Directly Unarchive Account'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        label="Action",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    reason = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
        label="Reason",
        help_text="Please provide a reason for this action."
    )
    
    def __init__(self, *args, **kwargs):
        """
        Initialize the form with account-specific and user-specific valid actions.
        """
        # Pop the account and user from kwargs before passing to super
        self.account = kwargs.pop('account', None)
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if not self.account:
            return
            
        # Determine available actions based on account status and user permissions
        available_actions = []
        
        # Logic for regular users (can request changes)
        if self.account.status == Account.STATUS_ACTIVE:
            available_actions.append(('request_archival', 'Request Account Archival'))
        elif self.account.status == Account.STATUS_ARCHIVED:
            available_actions.append(('request_unarchival', 'Request Account Unarchival'))
            
        # Logic for approvers (can approve/reject requests)
        if self.user and self.user.has_perm('accounts.approve_account_creation'):
            if self.account.status == Account.STATUS_PENDING_APPROVAL:
                available_actions.extend([
                    ('approve_creation', 'Approve Account Creation'),
                    ('reject_creation', 'Reject Account Creation'),
                ])
                
        if self.user and self.user.has_perm('accounts.approve_account_archival'):
            if self.account.status == Account.STATUS_PENDING_ARCHIVAL:
                available_actions.extend([
                    ('approve_archival', 'Approve Archival Request'),
                    ('reject_archival', 'Reject Archival Request'),
                ])
                
        if self.user and self.user.has_perm('accounts.approve_account_unarchival'):
            if self.account.status == Account.STATUS_PENDING_UNARCHIVAL:
                available_actions.extend([
                    ('approve_unarchival', 'Approve Unarchival Request'),
                    ('reject_unarchival', 'Reject Unarchival Request'),
                ])
        
        # Logic for admins (can perform direct actions)
        if self.user and self.user.is_superuser:
            # Add direct actions for admins - these bypass the normal workflow
            admin_actions = []
            
            if self.account.status != Account.STATUS_ACTIVE:
                admin_actions.append(('activate', 'Directly Activate Account'))
                
            if self.account.status != Account.STATUS_ARCHIVED:
                admin_actions.append(('archive', 'Directly Archive Account'))
                
            if self.account.status == Account.STATUS_ARCHIVED:
                admin_actions.append(('unarchive', 'Directly Unarchive Account'))
                
            if admin_actions:
                available_actions.append(('', '--- Admin Actions ---'))
                available_actions.extend(admin_actions)
        
        # Update the action field choices
        if available_actions:
            self.fields['action'].choices = available_actions
        else:
            # If no actions are available, provide a message
            self.fields['action'].choices = [('no_action', 'No actions available for this account')]
            self.fields['action'].disabled = True
            self.fields['reason'].disabled = True
            self.fields['reason'].required = False
            
    def clean(self):
        """
        Validate that the selected action is appropriate for the account status.
        """
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        
        if action == 'no_action':
            raise ValidationError("No valid actions are available for this account.")
            
        # Additional validations could be added here if needed
        # For example, checking if the user has permission for the selected action
            
        return cleaned_data
    
    def execute_action(self):
        """
        Execute the selected action on the account.
        
        Returns:
            bool: True if the action was successful, False otherwise.
        """
        if not self.is_valid():
            return False
            
        action = self.cleaned_data['action']
        reason = self.cleaned_data['reason']
        
        # Get user information for recording who performed the action
        user_identifier = f"{self.user.username} ({self.user.email})" if self.user else "System"
        
        # Execute the requested action
        try:
            if action == 'request_archival':
                return self.account.request_archival(reason=reason, requested_by=user_identifier)
            elif action == 'request_unarchival':
                return self.account.request_unarchival(reason=reason, requested_by=user_identifier)
            elif action == 'approve_creation':
                return self.account.approve_creation(reason=reason, approved_by=user_identifier)
            elif action == 'reject_creation':
                return self.account.reject_creation(reason=reason, approved_by=user_identifier)
            elif action == 'approve_archival':
                return self.account.approve_archival(reason=reason, approved_by=user_identifier)
            elif action == 'reject_archival':
                return self.account.reject_archival(reason=reason, approved_by=user_identifier)
            elif action == 'approve_unarchival':
                return self.account.approve_unarchival(reason=reason, approved_by=user_identifier)
            elif action == 'reject_unarchival':
                return self.account.reject_unarchival(reason=reason, approved_by=user_identifier)
            elif action == 'activate':
                return self.account.activate(reason=f"Direct activation: {reason}", approved_by=user_identifier)
            elif action == 'archive':
                return self.account.archive(reason=f"Direct archival: {reason}", approved_by=user_identifier)
            elif action == 'unarchive':
                return self.account.unarchive(reason=f"Direct unarchival: {reason}", approved_by=user_identifier)
            else:
                return False
        except ValidationError as e:
            # Add the error to the form
            self.add_error(None, str(e))
            return False


class AccountTypeForm(forms.ModelForm):
    """
    Form for creating and editing AccountType objects.
    
    This form handles the creation and editing of account types, such as
    Asset, Liability, Equity, Revenue, and Expense.
    """
    class Meta:
        model = AccountType
        fields = ['name', 'normal_balance', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'normal_balance': forms.Select(attrs={'class': 'form-select'}),
        }
        help_texts = {
            'normal_balance': 'The normal balance for this account type (Debit or Credit).',
        }
    
    def clean_name(self):
        """
        Validate the account type name.
        
        This method checks if:
        1. The name matches one of the predefined account types
        2. The name doesn't conflict with an existing account type (unless editing)
        """
        name = self.cleaned_data.get('name')
        
        # Define the set of valid account type names
        valid_account_types = {
            'Asset', 'Liability', 'Equity', 'Revenue', 'COGS', 
            'Operating Expense', 'G&A', 'Other'
        }
        
        # Check if the name is one of the valid account types
        if name not in valid_account_types:
            valid_types_str = ', '.join(sorted(valid_account_types))
            raise ValidationError(
                f"Account type must be one of: {valid_types_str}. "
                f"'{name}' is not a recognized account type."
            )
        
        # If we're editing an existing account type, and the name hasn't changed,
        # skip the uniqueness check because we know it's already valid
        if self.instance.pk and self.instance.name == name:
            return name
        
        # Check if an account type with this name already exists
        if AccountType.objects.filter(name=name).exists():
            raise ValidationError(f"An account type with the name '{name}' already exists.")
        
        return name


# You could also add a simple search form for filtering accounts
class AccountSearchForm(forms.Form):
    """
    Form for searching and filtering accounts.
    
    This form is used on the account list page to filter accounts
    by various criteria.
    """
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by number, name, or description...'
        })
    )
    
    status = forms.ChoiceField(
        required=False,
        choices=[('', 'All Statuses')] + Account.STATUS_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    account_type = forms.ModelChoiceField(
        required=False,
        queryset=AccountType.objects.all(),
        empty_label="All Account Types",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

class AccountBulkActionForm(forms.Form):
    """
    Form for performing bulk actions on multiple accounts.
    
    This form is used in the admin interface or list views to apply
    the same action to multiple selected accounts.
    """
    ACTION_CHOICES = [
        ('approve_all_pending', 'Approve All Pending Accounts'),
        ('approve_all_archival', 'Approve All Archival Requests'),
        ('approve_all_unarchival', 'Approve All Unarchival Requests'),
        ('reject_all_pending', 'Reject All Pending Accounts'),
        ('reject_all_archival', 'Reject All Archival Requests'),
        ('reject_all_unarchival', 'Reject All Unarchival Requests'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        label="Bulk Action",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    
    reason = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={'rows': 2, 'class': 'form-control'}),
        label="Reason",
        help_text="Please provide a reason for this bulk action."
    )
    
    def __init__(self, *args, **kwargs):
        """
        Initialize the form with user-specific permissions.
        """
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Filter actions based on user permissions
        if self.user:
            available_actions = []
            
            if self.user.has_perm('accounts.approve_account_creation'):
                available_actions.extend([
                    ('approve_all_pending', 'Approve All Pending Accounts'),
                    ('reject_all_pending', 'Reject All Pending Accounts'),
                ])
                
            if self.user.has_perm('accounts.approve_account_archival'):
                available_actions.extend([
                    ('approve_all_archival', 'Approve All Archival Requests'),
                    ('reject_all_archival', 'Reject All Archival Requests'),
                ])
                
            if self.user.has_perm('accounts.approve_account_unarchival'):
                available_actions.extend([
                    ('approve_all_unarchival', 'Approve All Unarchival Requests'),
                    ('reject_all_unarchival', 'Reject All Unarchival Requests'),
                ])
                
            if available_actions:
                self.fields['action'].choices = available_actions
            else:
                self.fields['action'].choices = [('no_action', 'No bulk actions available')]
                self.fields['action'].disabled = True
                self.fields['reason'].disabled = True
    
    def execute_bulk_action(self, queryset):
        """
        Execute the selected bulk action on the provided queryset of accounts.
        
        Args:
            queryset: QuerySet of Account objects to act upon
            
        Returns:
            tuple: (success_count, error_count, error_messages)
        """
        if not self.is_valid():
            return 0, 0, ["Form is not valid"]
            
        action = self.cleaned_data['action']
        reason = self.cleaned_data['reason']
        
        # Get user information
        user_identifier = f"{self.user.username} ({self.user.email})" if self.user else "System"
        
        success_count = 0
        error_count = 0
        error_messages = []
        
        # Execute the action on each account in the queryset
        for account in queryset:
            try:
                if action == 'approve_all_pending' and account.status == Account.STATUS_PENDING_APPROVAL:
                    if account.approve_creation(reason=reason, approved_by=user_identifier):
                        success_count += 1
                elif action == 'approve_all_archival' and account.status == Account.STATUS_PENDING_ARCHIVAL:
                    if account.approve_archival(reason=reason, approved_by=user_identifier):
                        success_count += 1
                elif action == 'approve_all_unarchival' and account.status == Account.STATUS_PENDING_UNARCHIVAL:
                    if account.approve_unarchival(reason=reason, approved_by=user_identifier):
                        success_count += 1
                elif action == 'reject_all_pending' and account.status == Account.STATUS_PENDING_APPROVAL:
                    if account.reject_creation(reason=reason, approved_by=user_identifier):
                        success_count += 1
                elif action == 'reject_all_archival' and account.status == Account.STATUS_PENDING_ARCHIVAL:
                    if account.reject_archival(reason=reason, approved_by=user_identifier):
                        success_count += 1
                elif action == 'reject_all_unarchival' and account.status == Account.STATUS_PENDING_UNARCHIVAL:
                    if account.reject_unarchival(reason=reason, approved_by=user_identifier):
                        success_count += 1
            except ValidationError as e:
                error_count += 1
                error_messages.append(f"Error with account {account.number}: {str(e)}")
                
        return success_count, error_count, error_messages