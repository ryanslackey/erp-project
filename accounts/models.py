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
    Examples: Cash, Accounts Receivable, Salaries Expense
    
    Accounts have three possible statuses:
    - ACTIVE: Available for use in transactions
    - ARCHIVED: Soft-deleted, preserved for historical reporting
    - PENDING: Newly created, awaiting approval
    """
    # Account status choices - simplified to just three options
    STATUS_ACTIVE = 'ACTIVE'
    STATUS_ARCHIVED = 'ARCHIVED'
    STATUS_PENDING = 'PENDING'
    
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_ARCHIVED, 'Archived'),
        (STATUS_PENDING, 'Pending Approval')
    ]
    
    # Valid status transitions dictionary - defines which statuses can transition to which other statuses
    VALID_STATUS_TRANSITIONS = {
        STATUS_ACTIVE: [STATUS_ARCHIVED],  # Active accounts can be archived
        STATUS_ARCHIVED: [STATUS_ACTIVE],  # Archived accounts can be restored to active
        STATUS_PENDING: [STATUS_ACTIVE, STATUS_ARCHIVED]  # Pending accounts can be approved or directly archived
    }
    
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
    account_type = models.ForeignKey(AccountType, on_delete=models.PROTECT)
    description = models.TextField(blank=True)
    parent = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='children')

    # Status fields
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,  # New accounts start as pending by default
        db_index=True,  # Add index for faster querying by status
    )
    is_active = models.BooleanField(default=False)  # Will be maintained automatically based on status
    status_change_date = models.DateField(null=True, blank=True)  # When the status last changed
    status_change_reason = models.TextField(blank=True)  # Reason for the last status change
    
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
        if new_status not in self.VALID_STATUS_TRANSITIONS.get(self.status, []):
            valid_statuses = ', '.join(self.VALID_STATUS_TRANSITIONS.get(self.status, []))
            raise ValidationError(
                f"Invalid status transition. Account with status '{self.status}' "
                f"can only transition to: {valid_statuses}"
            )
        return True
    
    def _change_status(self, new_status, reason='', change_date=None):
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
        self.save()
        
        # Create a status history record
        AccountStatusHistory.objects.create(
            account=self,
            status=new_status,
            effective_date=self.status_change_date,
            notes=f"Changed from {old_status} to {new_status}. {reason}".strip()
        )
        
        return True
    
    # Status transition methods
    def activate(self, reason=''):
        """
        Activate this account, making it available for use in transactions.
        This can be called for pending accounts (approval) or archived accounts (restoration).
        """
        return self._change_status(self.STATUS_ACTIVE, reason)
    
    def archive(self, reason='', archive_date=None):
        """
        Archive this account, recording when and why it was archived. 
        This is a "soft delete" that preserves historical data.
        """
        return self._change_status(self.STATUS_ARCHIVED, reason, archive_date)
    
    def unarchive(self, reason=''):
        """
        Restore an archived account to active status.
        This is a convenience alias for activate() with a clearer name for this specific transition.
        """
        return self._change_status(self.STATUS_ACTIVE, f"Unarchived. {reason}")
    
    def approve(self, reason=''):
        """
        Approve a pending account, making it active.
        This is a convenience alias for activate() with a clearer name for this specific transition.
        """
        if self.status != self.STATUS_PENDING:
            raise ValidationError("Only pending accounts can be approved.")
        
        return self._change_status(self.STATUS_ACTIVE, f"Approved. {reason}")
    
    def reject(self, reason=''):
        """
        Reject a pending account by archiving it directly.
        Unlike the previous version, rejected accounts now go straight to archived status.
        """
        if self.status != self.STATUS_PENDING:
            raise ValidationError("Only pending accounts can be rejected.")
        
        return self._change_status(self.STATUS_ARCHIVED, f"Rejected. {reason}")
    
    # Convenience query methods
    def was_active_on_date(self, check_date):
        """
        Determine if this account was active on a specific date.
        Uses the status history to determine the status accurately.
        """
        if self.created_at.date() > check_date:
            return False  # Account didn't exist yet
            
        # Use the status history class to get the status on that date
        status_on_date = AccountStatusHistory.get_status_on_date(self, check_date)
        return status_on_date == self.STATUS_ACTIVE
    
    def get_status_on_date(self, check_date):
        """
        Return the detailed status of this account on a specific date.
        """
        if self.created_at.date() > check_date:
            return None  # Account didn't exist yet
        
        return AccountStatusHistory.get_status_on_date(self, check_date)

class AccountStatusHistory(models.Model):
    """
    Tracks the complete history of status changes for an account over time.
    This allows for accurate point-in-time reporting and auditing.
    """
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='status_history')
    # Use the same status choices as the Account model for consistency
    status = models.CharField(
        max_length=20,
        choices=Account.STATUS_CHOICES
    )
    effective_date = models.DateField()
    notes = models.TextField(blank=True)
    created_by = models.CharField(max_length=100, blank=True)  # Could be a ForeignKey to User
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['-effective_date', '-created_at']
        verbose_name_plural = 'Account status histories'
        # Add database index for faster historical queries
        indexes = [
            models.Index(fields=['account', 'effective_date']),
        ]
    
    def __str__(self):
        return f"{self.account} - {self.status} on {self.effective_date}"
    
    @classmethod
    def get_status_on_date(cls, account, check_date):
        """ 
        Returns the status of an account on a specific date based on the history.
        This is a critical method for historical reporting accuracy.
        """
        status_record = cls.objects.filter(
            account=account,
            effective_date__lte=check_date
        ).order_by('-effective_date', '-created_at').first()
        
        # If no status record exists for this date but the account existed,
        # assume it was pending (the default state for new accounts)
        if not status_record and account.created_at.date() <= check_date:
            return Account.STATUS_PENDING
        
        # If no status record and account didn't exist yet, return None
        if not status_record:
            return None
            
        return status_record.status
    
    @classmethod
    def get_accounts_by_status_on_date(cls, status, check_date):
        """
        Returns a QuerySet of accounts that had the specified status on the given date.
        This is useful for point-in-time reporting.
        """
        # Get the latest status record before or on the check date for each account
        subquery = cls.objects.filter(
            effective_date__lte=check_date
        ).order_by('account', '-effective_date').distinct('account')
        
        # Filter to only those with the desired status
        matching_history_ids = subquery.filter(status=status).values_list('id', flat=True)
        
        # Get the actual accounts from the matching history records
        account_ids = cls.objects.filter(id__in=matching_history_ids).values_list('account_id', flat=True)
        
        return Account.objects.filter(id__in=account_ids)
    
    @classmethod
    def create_initial_status(cls, account):
        """
        Creates the initial status history record for a new account.
        This should be called when an account is created.
        """
        return cls.objects.create(
            account=account,
            status=account.status,
            effective_date=timezone.now().date(),
            notes="Initial account creation"
        )

# Signal to automatically create an initial status history record when an account is created
@receiver(post_save, sender=Account)
def create_account_status_history(sender, instance, created, **kwargs):
    """
    Signal handler to automatically create an initial status history record
    when a new Account is created.
    """
    if created:  # Only run this for newly created accounts
        AccountStatusHistory.create_initial_status(instance)