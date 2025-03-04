# Generated by Django 5.1.6 on 2025-03-04 20:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='account',
            name='status',
            field=models.CharField(choices=[('ACTIVE', 'Active'), ('ARCHIVED', 'Archived'), ('PENDING', 'Pending Approval')], db_index=True, default='PENDING', max_length=20),
        ),
        migrations.AlterField(
            model_name='accountstatushistory',
            name='status',
            field=models.CharField(choices=[('ACTIVE', 'Active'), ('ARCHIVED', 'Archived'), ('PENDING', 'Pending Approval')], max_length=20),
        ),
    ]
