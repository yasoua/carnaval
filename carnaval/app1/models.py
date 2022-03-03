from django.db import models
import barcode
import os
from barcode.writer import ImageWriter
from io import BytesIO
from uuid import uuid4
from django.core.files.base import ContentFile, File



# Create your models here.
def image_path_and_rename(instance, filename):
    upload_to = 'images'
    ext = filename.split('.')[-1]
    # get filename
    if instance.pk:
        filename = '{}.{}'.format(instance.pk, ext)
    else:
        # set filename as random string
        filename = '{}.{}'.format(uuid4().hex, ext)
    # return the whole path to the file
    return os.path.join(upload_to, filename)

class user(models.Model):
    name = models.CharField(max_length=200)
    picture = models.FileField(upload_to=image_path_and_rename)
    barcode = models.ImageField(upload_to='images/', blank=True)
    country_id = models.CharField(max_length=1, null=True)
    manufacturer_id = models.CharField(max_length=6, null=True)
    product_id = models.CharField(max_length=5, null=True)

    def __str__(self):
        return str(self.name)

    def save(self, *args, **kwargs):
        EAN = barcode.get_barcode_class('ean13')
        with open(f'{self.picture}.jpg','w') as f:
            ean = EAN(f'{self.country_id}{self.manufacturer_id}{self.product_id}', writer=ImageWriter().write(self,f))
        buffer = BytesIO()
        ean.write(buffer)
        self.barcode.save(f'{self.name}.png', File(buffer), save=False)
        return super().save(*args, **kwargs)