from django.db import models


class Station(models.Model):
    truckstop_id = models.IntegerField(unique=True)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=300)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    price = models.FloatField()  # USD per gallon
    lat = models.FloatField()
    lng = models.FloatField()

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state})"
