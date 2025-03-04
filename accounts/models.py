from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator
from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.dispatch import receiver

# Create your models here.

def validate_account_number_range(value, account_type):
    """
    Validates that the account number falls within the appropriate range
    based on the account type.
    """
    # Convert to integer for range comparison
    try:
        account_num = int(value)
    except ValueError:
        raise ValidationError('Account number must be numeric.')
    
    # Define the valid ranges for each account type
    account_ranges = {
        'Asset': (100000, 199999),
        'Liability': (200000, 289999),
        'Equity': (290000, 299999),
        'Revenue': (300000, 399999),
        'COGS': (400000, 499999),
        'Operating Expense': (500000, 599999),
        'G&A': (600000, 699999),
        'Other': (700000, 799999),
    }
    
    # Check if the account type name is in our defined ranges
    if account_type.name not in account_ranges:
        raise ValidationError(f"Unknown account type: {account_type.name}")
    
    # Get the valid range for this account type
    min_val, max_val = account_ranges[account_type.name]
    
    # Check if the account number is within the valid range
    if not (min_val <= account_num <= max_val):
        raise ValidationError(
            f"Account number {value} is not valid for {account_type.name} accounts. "
            f"Must be between {min_val} and {max_val}."
        )

class AccountType(models.Model):
    """
    Represents categories of accounts in the Chart of Accounts.
    Examples: Asset, Liability, Equity, Revenue, Expense
    """
    name = models.CharField(max_length=50, unique=True)
    # Determines whether accounts of this type typically have debit or credit balances
    normal_balance = models.CharField(
        max_length=6,
        choices=[('DEBIT', 'Debit'), ('CREDIT', 'Credit')],
    )
    description = models.TextField(blank=True)
    
    def __str__(self):
        return self.name
    
class Account(models.Model):
    """
    Represents individual accounts in the Chart of Accounts.
    
    Accounts have the following possible statuses:
    - ACTIVE: Available for use in transactions
    - ARCHIVED: Soft-deleted, preserved for historical reporting
    - PENDING_APPROVAL: Newly created, awaiting approval
    - PENDING_ARCHIVAL: Active account with request to archive, awaiting approval
    - PENDING_UNARCHIVAL: Archived account with request to unarchive, awaiting approval
    """
    # Account status choices - expanded to include pending approval states
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_ARCHIVED = 'ARCHIVED'
    STATUS_PENDING_APPROVAL = 'PENDING_APPROVAL'
    STATUS_PENDING_ARCHIVAL = 'PENDING_ARCHIVAL'
    STATUS_PENDING_UNARCHIVAL = 'PENDING_UNARCHIVAL'
    
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_ARCHIVED, 'Archived'),
        (STATUS_PENDING_APPROVAL, 'Pending Approval'),
        (STATUS_PENDING_ARCHIVAL, 'Pending Archival'),
        (STATUS_PENDING_UNARCHIVAL, 'Pending Unarchival')
    ]
    
    # Valid status transitions dictionary - defines which statuses can transition to which other statuses
    VALID_STATUS_TRANSITIONS = {
        STATUS_ACTIVE: [STATUS_ARCHIVED, STATUS_PENDING_ARCHIVAL],
        STATUS_ARCHIVED: [STATUS_ACTIVE, STATUS_PENDING_UNARCHIVAL],
        STATUS_PENDING_APPROVAL: [STATUS_ACTIVE, STATUS_ARCHIVED],
        STATUS_PENDING_ARCHIVAL: [STATUS_ACTIVE, STATUS_ARCHIVED],
        STATUS_PENDING_UNARCHIVAL: [STATUS_ACTIVE, STATUS_ARCHIVED]
    }
    
    # Fields remain the same as before
    number = models.CharField(
        max_length=6,
        unique=True,
        validators=[
            RegexValidator(
                regex=r'^\d{6}$',
                message='Account number must be exactly 6 digits.',
                code='invalid_account_number'
            )
        ]
    )
    name = models.CharField(max_length=100)
    account_type = models.ForeignKey('AccountType', on_delete=models.PROTECT)
    description = models.TextField(blank=True)
    parent = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='children')

    # Status fields
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING_APPROVAL,  # New accounts start as pending by default
        db_index=True,  # Add index for faster querying by status
    )
    is_active = models.BooleanField(default=False)  # Will be maintained automatically based on status
    status_change_date = models.DateField(null=True, blank=True)  # When the status last changed
    status_change_reason = models.TextField(blank=True)  # Reason for the last status change
    
    # New fields for approval workflow
    requested_by = models.CharField(max_length=100, blank=True)  # Who requested the status change
    requested_date = models.DateTimeField(null=True, blank=True)  # When the status change was requested
    approved_by = models.CharField(max_length=100, blank=True)  # Who approved the status change
    approved_date = models.DateTimeField(null=True, blank=True)  # When the status change was approved
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.number} - {self.name}"
    
    class Meta:
        ordering = ['number']
    
    def save(self, *args, **kwargs):
        """
        Override save method to automatically update is_active based on status.
        """
        # Automatically update is_active based on status
        self.is_active = self.status == self.STATUS_ACTIVE
        super().save(*args, **kwargs)
    
    def _validate_status_transition(self, new_status):
        """
        Private method to validate that a status transition is allowed.
        Raises ValidationError if the transition is not valid.
        """
        # First check if the new_status is a valid status at all
        valid_statuses = [status[0] for status in self.STATUS_CHOICES]
        if new_status not in valid_statuses:
            raise ValidationError(f"'{new_status}' is not a valid status. Valid statuses are: {', '.join(valid_statuses)}")
        
        # Then check if the transition is allowed
        if new_status not in self.VALID_STATUS_TRANSITIONS.get(self.status, []):
            valid_transitions = ', '.join(self.VALID_STATUS_TRANSITIONS.get(self.status, []))
            raise ValidationError(
                f"Invalid status transition. Account with status '{self.status}' "
                f"can only transition to: {valid_transitions}"
            )
        return True
    
    def _change_status(self, new_status, reason='', change_date=None, requested_by='', approved_by=''):
        """
        Private method to handle the common status change logic.
        """
        # Validate the status transition
        self._validate_status_transition(new_status)
        
        # If we're already in this status, do nothing
        if self.status == new_status:
            return False
        
        # Set the new status and related fields
        old_status = self.status
        self.status = new_status
        self.status_change_date = change_date or timezone.now().date()
        self.status_change_reason = reason
        
        # Record approval information if provided
        if requested_by:
            self.requested_by = requested_by
            self.requested_date = timezone.now()
        
        if approved_by:
            self.approved_by = approved_by
            self.approved_date = timezone.now()
            
        self.save()
        
        # Create a status history record
        notes = f"Changed from {old_status} to {new_status}. {reason}".strip()
        if requested_by and approved_by:
            notes += f" Requested by {requested_by}. Approved by {approved_by}."
        elif requested_by:
            notes += f" Requested by {requested_by}."
            
        AccountStatusHistory.objects.create(
            account=self,
            status=new_status,
            effective_date=self.status_change_date,
            notes=notes,
            created_by=approved_by if approved_by else requested_by
        )
        
        return True
    
    # -- REQUEST METHODS -- #
    
    def request_archival(self, reason='', requested_by=''):
        """
        Request to archive an active account. 
        Transitions account from ACTIVE to PENDING_ARCHIVAL status.
        """
        if self.status != self.STATUS_ACTIVE:
            raise ValidationError("Only active accounts can be requested for archival.")
        
        return self._change_status(self.STATUS_PENDING_ARCHIVAL, 
                                 f"Archival requested. {reason}", 
                                 requested_by=requested_by)
    
    def request_unarchival(self, reason='', requested_by=''):
        """
        Request to unarchive an archived account.
        Transitions account from ARCHIVED to PENDING_UNARCHIVAL status.
        """
        if self.status != self.STATUS_ARCHIVED:
            raise ValidationError("Only archived accounts can be requested for unarchival.")
        
        return self._change_status(self.STATUS_PENDING_UNARCHIVAL, 
                                 f"Unarchival requested. {reason}", 
                                 requested_by=requested_by)
    
    # -- APPROVAL METHODS -- #
    
    def approve_creation(self, reason='', approved_by=''):
        """
        Approve a pending account, making it active.
        """
        if self.status != self.STATUS_PENDING_APPROVAL:
            raise ValidationError("Only pending accounts can be approved for creation.")
        
        return self._change_status(self.STATUS_ACTIVE, 
                                 f"Creation approved. {reason}", 
                                 approved_by=approved_by)
    
    def approve_archival(self, reason='', approved_by=''):
        """
        Approve an archival request for an account.
        Transitions from PENDING_ARCHIVAL to ARCHIVED.
        """
        if self.status != self.STATUS_PENDING_ARCHIVAL:
            raise ValidationError("Only accounts pending archival can be approved for archival.")
        
        return self._change_status(self.STATUS_ARCHIVED, 
                                 f"Archival approved. {reason}", 
                                 approved_by=approved_by)
    
    def approve_unarchival(self, reason='', approved_by=''):
        """
        Approve an unarchival request for an account.
        Transitions from PENDING_UNARCHIVAL to ACTIVE.
        """
        if self.status != self.STATUS_PENDING_UNARCHIVAL:
            raise ValidationError("Only accounts pending unarchival can be approved for unarchival.")
        
        return self._change_status(self.STATUS_ACTIVE, 
                                 f"Unarchival approved. {reason}", 
                                 approved_by=approved_by)
    
    # -- REJECTION METHODS -- #
    
    def reject_creation(self, reason='', approved_by=''):
        """
        Reject a pending account by completely deleting it from the system.
        This frees up the account number for future use.
        """
        if self.status != self.STATUS_PENDING_APPROVAL:
            raise ValidationError("Only pending accounts can be rejected.")
        
        # Log the rejection before deletion
        account_number = self.number
        account_name = self.name
        
        # Delete the account and all related history
        self.delete()
        
        # Could log this action to a separate audit table if needed
        
        return True
    
    def reject_archival(self, reason='', approved_by=''):
        """
        Reject an archival request, returning account to ACTIVE status.
        """
        if self.status != self.STATUS_PENDING_ARCHIVAL:
            raise ValidationError("Only accounts pending archival can have their request rejected.")
        
        return self._change_status(self.STATUS_ACTIVE, 
                                 f"Archival request rejected. {reason}", 
                                 approved_by=approved_by)
    
    def reject_unarchival(self, reason='', approved_by=''):
        """
        Reject an unarchival request, returning account to ARCHIVED status.
        """
        if self.status != self.STATUS_PENDING_UNARCHIVAL:
            raise ValidationError("Only accounts pending unarchival can have their request rejected.")
        
        return self._change_status(self.STATUS_ARCHIVED, 
                                 f"Unarchival request rejected. {reason}", 
                                 approved_by=approved_by)
    
    # -- DIRECT ACTION METHODS (FOR BACKWARD COMPATIBILITY OR ADMIN USE) -- #
    
    def activate(self, reason='', approved_by=''):
        """
        Directly activate this account, bypassing approval workflow.
        This should only be used by admins or for backward compatibility.
        """
        if self.status not in [self.STATUS_PENDING_APPROVAL, self.STATUS_ARCHIVED, self.STATUS_PENDING_UNARCHIVAL]:
            raise ValidationError("Account status cannot be changed to active from its current status.")
            
        return self._change_status(self.STATUS_ACTIVE, f"Directly activated. {reason}", approved_by=approved_by)
    
    def archive(self, reason='', approved_by='', archive_date=None):
        """
        Directly archive this account, bypassing approval workflow.
        This should only be used by admins or for backward compatibility.
        """
        if self.status not in [self.STATUS_ACTIVE, self.STATUS_PENDING_ARCHIVAL, self.STATUS_PENDING_APPROVAL]:
            raise ValidationError("Account status cannot be changed to archived from its current status.")
            
        return self._change_status(self.STATUS_ARCHIVED, f"Directly archived. {reason}", 
                                 change_date=archive_date, approved_by=approved_by)
    
    def unarchive(self, reason='', approved_by=''):
        """
        Directly unarchive an account, bypassing approval workflow.
        This should only be used by admins or for backward compatibility.
        """
        if self.status != self.STATUS_ARCHIVED and self.status != self.STATUS_PENDING_UNARCHIVAL:
            raise ValidationError("Only archived accounts or accounts pending unarchival can be unarchived.")
            
        return self._change_status(self.STATUS_ACTIVE, f"Directly unarchived. {reason}", approved_by=approved_by)
    
    # Legacy method names for backward compatibility
    def approve(self, reason='', approved_by=''):
        """Legacy method, maps to approve_creation"""
        return self.approve_creation(reason, approved_by)
        
    def reject(self, reason='', approved_by=''):
        """Legacy method, maps to reject_creation"""
        return self.reject_creation(reason, approved_by)

class AccountStatusHistory(models.Model):
    """
    Tracks the complete history of status changes for an account over time.
    """
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='status_history')
    # Update to use the same expanded status choices as the Account model
    status = models.CharField(
        max_length=20,
        choices=Account.STATUS_CHOICES
    )
    effective_date = models.DateField()
    notes = models.TextField(blank=True)
    created_by = models.CharField(max_length=100, blank=True)
    
    # Add fields to track approval information
    requested_by = models.CharField(max_length=100, blank=True)
    approved_by = models.CharField(max_length=100, blank=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['-effective_date', '-created_at']
        verbose_name_plural = 'Account status histories'
        indexes = [
            models.Index(fields=['account', 'effective_date']),
        ]
    
    # Update get_status_on_date to handle the new status types
    @classmethod
    def get_status_on_date(cls, account, check_date):
        """
        Returns the status of an account on a specific date.
        For reporting purposes, pending statuses are treated as their previous state.
        """
        status_record = cls.objects.filter(
            account=account,
            effective_date__lte=check_date
        ).order_by('-effective_date', '-created_at').first()
        
        if not status_record and account.created_at.date() <= check_date:
            return Account.STATUS_PENDING_APPROVAL
        
        if not status_record:
            return None
            
        # For reporting, treat pending statuses as their underlying state
        status = status_record.status
        if status == Account.STATUS_PENDING_ARCHIVAL:
            return Account.STATUS_ACTIVE
        elif status == Account.STATUS_PENDING_UNARCHIVAL:
            return Account.STATUS_ARCHIVED
            
        return status