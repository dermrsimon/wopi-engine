# Generated by Django 3.1.2 on 2021-03-06 21:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('insurancesubmission', '0005_auto_20210306_2154'),
    ]

    operations = [
        migrations.AddField(
            model_name='insurancesubmission',
            name='status',
            field=models.CharField(default='w', max_length=1),
        ),
    ]