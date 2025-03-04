from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from .models import Account, AccountType, AccountStatusHistory

class AccountModelTests(TestCase):
    """Tests for the Account model."""
    
    def setUp(self):
        """Set up test data."""
        # Create account types
        self.asset_type = AccountType.objects.create(
            name='Asset',
            normal_balance='DEBIT',
            description='Resources owned by the business'
        )
        self.liability_type = AccountType.objects.create(
            name='Liability',
            normal_balance='CREDIT',
            description='Obligations of the business'
        )
        
        # Create a test account
        self.test_account = Account.objects.create(
            number='101000',
            name='Test Cash Account',
            account_type=self.asset_type,
            description='Test account for cash',
            status=Account.STATUS_PENDING
        )
    
    def test_account_creation(self):
        """Test that an account is created correctly."""
        self.assertEqual(self.test_account.number, '101000')
        self.assertEqual(self.test_account.name, 'Test Cash Account')
        self.assertEqual(self.test_account.account_type, self.asset_type)
        self.assertEqual(self.test_account.status, Account.STATUS_PENDING)
        self.assertFalse(self.test_account.is_active)
    
    def test_account_status_transitions(self):
        """Test account status transitions."""
        # Test approving a pending account
        self.test_account.approve('Testing approval')
        self.assertEqual(self.test_account.status, Account.STATUS_ACTIVE)
        self.assertTrue(self.test_account.is_active)
        
        # Test archiving an active account
        self.test_account.archive('Testing archival')
        self.assertEqual(self.test_account.status, Account.STATUS_ARCHIVED)
        self.assertFalse(self.test_account.is_active)
        
        # Test unarchiving (restoring) an archived account
        self.test_account.unarchive('Testing restoration')
        self.assertEqual(self.test_account.status, Account.STATUS_ACTIVE)
        self.assertTrue(self.test_account.is_active)
        
        # Test invalid transition (should raise ValidationError)
        with self.assertRaises(ValidationError):
            # Create a new account in pending status
            new_account = Account.objects.create(
                number='102000',
                name='Another Test Account',
                account_type=self.asset_type,
                status=Account.STATUS_PENDING
            )
            # Try to archive without first activating (not allowed)
            new_account.unarchive('This should fail')
    
    def test_account_status_history(self):
        """Test that status history is recorded correctly."""
        self.test_account.approve('Testing approval')
        self.test_account.archive('Testing archival')
        
        # Get status history records
        history = AccountStatusHistory.objects.filter(account=self.test_account)
        
        # Should have 3 records: initial creation, approval, and archival
        self.assertEqual(history.count(), 3)
        
        # Check the status sequence
        statuses = [record.status for record in history.order_by('created_at')]
        self.assertEqual(statuses, [
            Account.STATUS_PENDING,
            Account.STATUS_ACTIVE,
            Account.STATUS_ARCHIVED
        ])
    
    def test_account_number_validation(self):
        """Test account number validation rules."""
        # Test valid account number for asset (100000-199999)
        valid_account = Account(
            number='150000',
            name='Valid Asset Account',
            account_type=self.asset_type
        )
        valid_account.full_clean()  # Should not raise error
        
        # Test invalid account number for asset (outside valid range)
        invalid_account = Account(
            number='250000',  # This is in the liability range
            name='Invalid Asset Account',
            account_type=self.asset_type
        )
        with self.assertRaises(ValidationError):
            from .validators import validate_account_number_range
            validate_account_number_range(invalid_account.number, invalid_account.account_type)


class AccountViewTests(TestCase):
    """Tests for account views."""
    
    def setUp(self):
        """Set up test data and authenticated client."""
        # Create account types
        self.asset_type = AccountType.objects.create(
            name='Asset',
            normal_balance='DEBIT'
        )
        
        # Create test accounts
        self.active_account = Account.objects.create(
            number='101000',
            name='Active Account',
            account_type=self.asset_type,
            status=Account.STATUS_ACTIVE
        )
        
        self.pending_account = Account.objects.create(
            number='102000',
            name='Pending Account',
            account_type=self.asset_type,
            status=Account.STATUS_PENDING
        )
        
        # Create a test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpassword'
        )
        
        # Create an authenticated client
        self.client = Client()
        self.client.login(username='testuser', password='testpassword')
    
    def test_account_list_view(self):
        """Test the account list view."""
        response = self.client.get(reverse('accounts:account_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/account_list.html')
        self.assertContains(response, 'Active Account')
        self.assertContains(response, 'Pending Account')
    
    def test_account_detail_view(self):
        """Test the account detail view."""
        response = self.client.get(
            reverse('accounts:account_detail', args=[self.active_account.number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/account_detail.html')
        self.assertContains(response, 'Active Account')
        self.assertContains(response, '101000')
    
    def test_account_create_view(self):
        """Test the account creation view and form."""
        # Get the form page
        response = self.client.get(reverse('accounts:account_create'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/account_form.html')
        
        # Submit the form with valid data
        response = self.client.post(
            reverse('accounts:account_create'),
            {
                'number': '103000',
                'name': 'New Test Account',
                'account_type': self.asset_type.id,
                'description': 'Created in test',
                'parent': '',  # No parent
            },
            follow=True  # Follow redirects
        )
        
        # Check that account was created
        self.assertContains(response, 'New Test Account')
        self.assertTrue(Account.objects.filter(number='103000').exists())
    
    def test_account_edit_view(self):
        """Test the account edit view and form."""
        # Get the form page
        response = self.client.get(
            reverse('accounts:account_edit', args=[self.active_account.number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/account_form.html')
        
        # Submit the form with updated data
        response = self.client.post(
            reverse('accounts:account_edit', args=[self.active_account.number]),
            {
                'number': self.active_account.number,  # Number shouldn't change
                'name': 'Updated Account Name',
                'account_type': self.asset_type.id,
                'description': 'Updated in test',
                'parent': '',  # No parent
            },
            follow=True  # Follow redirects
        )
        
        # Check that account was updated
        self.assertContains(response, 'Updated Account Name')
        self.active_account.refresh_from_db()
        self.assertEqual(self.active_account.name, 'Updated Account Name')
    
    def test_account_status_change_view(self):
        """Test the account status change view and form."""
        # Get the form page
        response = self.client.get(
            reverse('accounts:account_status_change', args=[self.active_account.number])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'accounts/account_status_form.html')
        
        # Submit the form to archive the account
        response = self.client.post(
            reverse('accounts:account_status_change', args=[self.active_account.number]),
            {
                'new_status': Account.STATUS_ARCHIVED,
                'reason': 'Testing status change',
            },
            follow=True  # Follow redirects
        )
        
        # Check that account status was changed
        self.active_account.refresh_from_db()
        self.assertEqual(self.active_account.status, Account.STATUS_ARCHIVED)
        self.assertFalse(self.active_account.is_active)
