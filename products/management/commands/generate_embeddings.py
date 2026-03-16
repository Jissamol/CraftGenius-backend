import os
from django.core.management.base import BaseCommand
from products.models import Product, ProductEmbedding
from fastembed import TextEmbedding

class Command(BaseCommand):
    help = 'Generates vector embeddings for all existing products using local fastembed'

    def handle(self, *args, **kwargs):
        self.stdout.write('Initializing fastembed model (this may take a moment to download the model on first run)...')
        # This uses BAAI/bge-small-en-v1.5 locally, totally free!
        embedding_model = TextEmbedding()
        
        products = Product.objects.all()
        count = 0

        self.stdout.write(f'Found {products.count()} products. Generating embeddings locally...')

        # Collect text to embed in a batch for speed
        texts_to_embed = []
        product_list = list(products)

        for product in product_list:
            artisan = getattr(product.seller, 'seller_profile', None)
            craft_specialty = artisan.craft_specialty if artisan and artisan.craft_specialty else 'Handcrafted'
            location = artisan.location if artisan and artisan.location else 'Unknown'
            category_name = product.category.name if product.category else 'Uncategorized'
            
            text_content = f"""
Product: {product.name}
Category: {category_name}
Description: {product.description}
Tags: {product.tags}
Artisan Specialty: {craft_specialty}
Artisan Location: {location}
Price: {product.price}
"""
            texts_to_embed.append(text_content.strip())

        if not product_list:
            self.stdout.write('No products found to embed.')
            return

        # Generate embeddings in bulk
        embeddings = list(embedding_model.embed(texts_to_embed))

        for idx, product in enumerate(product_list):
            vector = embeddings[idx].tolist()
            text_content = texts_to_embed[idx]
            
            ProductEmbedding.objects.update_or_create(
                product=product,
                defaults={
                    'vector': vector,
                    'text_content': text_content
                }
            )
            count += 1
            self.stdout.write(self.style.SUCCESS(f'Successfully embedded: {product.name}'))

        self.stdout.write(self.style.SUCCESS(f'Finished generating embeddings for {count} products offline!'))
