# Generated by Django 3.1.2 on 2020-11-18 12:19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('insurance', '0002_insurance_insurance_key'),
    ]

    operations = [
        migrations.AlterField(
            model_name='insurance',
            name='insurance_key',
            field=models.CharField(max_length=30, unique=True),
        ),
    ]