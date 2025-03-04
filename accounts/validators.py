from django.core.exceptions import ValidationError

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