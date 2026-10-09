import os
import math
import numpy as np
from django.db.models import Avg, Count, Q
from django.utils import timezone
from datetime import timedelta

from .models import (
    Product, ProductEmbedding, Order, Wishlist, CartItem,
    BrowsingHistory, UserCategoryInterest, Category
)


def cosine_similarity_vec(v1, v2):
    """Calculate cosine similarity between two 1D numpy arrays."""
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    sim = np.dot(v1, v2) / (norm1 * norm2)
    # Clamp to [0.0, 1.0] for recommendation scoring
    return max(0.0, float(sim))


def record_product_view(user, product):
    """
    Records a product view in BrowsingHistory and increments category affinity.
    Safe to call with unauthenticated user (no-op).
    """
    if not user or not user.is_authenticated or not product:
        return

    history, created = BrowsingHistory.objects.get_or_create(
        user=user,
        product=product,
        defaults={'view_count': 1}
    )
    if not created:
        history.view_count += 1
        history.last_viewed_at = timezone.now()
        history.save(update_fields=['view_count', 'last_viewed_at'])

    # Boost category interest
    if product.category:
        interest, c_created = UserCategoryInterest.objects.get_or_create(
            user=user,
            category=product.category,
            defaults={'score': 1.0}
        )
        if not c_created:
            interest.score = round(interest.score + 0.4, 2)
            interest.save(update_fields=['score', 'updated_at'])


def boost_category_interest(user, category, points=1.0):
    """Helper to boost a user's category interest upon cart, wishlist, or order action."""
    if not user or not user.is_authenticated or not category:
        return
    interest, created = UserCategoryInterest.objects.get_or_create(
        user=user,
        category=category,
        defaults={'score': float(points)}
    )
    if not created:
        interest.score = round(interest.score + float(points), 2)
        interest.save(update_fields=['score', 'updated_at'])


class RecommendationEngine:
    """
    Intelligent AI Recommendation Engine combining:
    - Interaction signals (Browsing, Wishlist, Purchases, Cart, Category Interests)
    - Semantic similarity using local fastembed product vector embeddings
    - Dynamic personalized explanations (e.g. "Recommended because you like handmade pottery")
    - Intelligent cold-start fallback recommendations for new users
    """

    @classmethod
    def get_user_interactions(cls, user):
        """
        Collects all interacted products with associated intent weights and source metadata.
        Returns:
            interactions: dict of {product_id: {'product': Product, 'weight': float, 'source': str, 'views': int}}
            purchased_ids: set of product IDs already purchased
            category_scores: dict of {category_id: float}
        """
        interactions = {}
        purchased_ids = set()
        category_scores = {}

        if not user or not user.is_authenticated:
            return interactions, purchased_ids, category_scores

        # 1. Purchases (Highest intent: weight 4.0)
        orders = Order.objects.filter(customer=user).select_related('product', 'product__category')
        for ord_item in orders:
            prod = ord_item.product
            if prod:
                purchased_ids.add(prod.id)
                interactions[prod.id] = {
                    'product': prod,
                    'weight': 4.0,
                    'source': 'purchase',
                    'views': 1
                }
                if prod.category_id:
                    category_scores[prod.category_id] = category_scores.get(prod.category_id, 0.0) + 4.0

        # 2. Wishlist (High intent: weight 2.5)
        wishlist_items = Wishlist.objects.filter(user=user).select_related('product', 'product__category')
        for item in wishlist_items:
            prod = item.product
            if prod:
                current_weight = interactions.get(prod.id, {}).get('weight', 0.0)
                if current_weight < 2.5:
                    interactions[prod.id] = {
                        'product': prod,
                        'weight': 2.5,
                        'source': 'wishlist',
                        'views': 1
                    }
                if prod.category_id:
                    category_scores[prod.category_id] = category_scores.get(prod.category_id, 0.0) + 2.5

        # 3. Cart Items (High intent: weight 2.0)
        cart_items = CartItem.objects.filter(cart__user=user).select_related('product', 'product__category')
        for item in cart_items:
            prod = item.product
            if prod:
                current_weight = interactions.get(prod.id, {}).get('weight', 0.0)
                if current_weight < 2.0:
                    interactions[prod.id] = {
                        'product': prod,
                        'weight': 2.0,
                        'source': 'cart',
                        'views': 1
                    }
                if prod.category_id:
                    category_scores[prod.category_id] = category_scores.get(prod.category_id, 0.0) + 2.0

        # 4. Browsing History (Explicit views: weight 1.2 to 2.2 based on view_count)
        history_items = BrowsingHistory.objects.filter(user=user).select_related('product', 'product__category')
        for item in history_items:
            prod = item.product
            if prod:
                browse_weight = min(2.2, 1.2 + 0.3 * math.log1p(item.view_count))
                current_weight = interactions.get(prod.id, {}).get('weight', 0.0)
                if current_weight < browse_weight:
                    interactions[prod.id] = {
                        'product': prod,
                        'weight': browse_weight,
                        'source': 'browsing',
                        'views': item.view_count
                    }
                if prod.category_id:
                    category_scores[prod.category_id] = category_scores.get(prod.category_id, 0.0) + (1.0 * min(3, item.view_count))

        # 5. User Category Interests
        cat_interests = UserCategoryInterest.objects.filter(user=user)
        for ci in cat_interests:
            category_scores[ci.category_id] = category_scores.get(ci.category_id, 0.0) + (1.5 * ci.score)

        return interactions, purchased_ids, category_scores

    @classmethod
    def compute_user_taste_vector(cls, interactions):
        """
        Builds a normalized weighted centroid embedding vector representing the user's taste.
        Returns:
            user_vector: np.ndarray (normalized) or None
            interacted_vectors: dict of {product_id: (vector, product, source)}
        """
        if not interactions:
            return None, {}

        product_ids = list(interactions.keys())
        embeddings = ProductEmbedding.objects.filter(product_id__in=product_ids)
        emb_map = {emb.product_id: np.array(emb.vector, dtype=np.float32) for emb in embeddings if emb.vector}

        weighted_sum = None
        total_weight = 0.0
        interacted_vectors = {}

        for pid, data in interactions.items():
            vec = emb_map.get(pid)
            if vec is not None and len(vec) > 0:
                w = data['weight']
                interacted_vectors[pid] = (vec, data['product'], data['source'])
                if weighted_sum is None:
                    weighted_sum = vec * w
                else:
                    weighted_sum += vec * w
                total_weight += w

        if weighted_sum is not None and total_weight > 0:
            norm = np.linalg.norm(weighted_sum)
            if norm > 0:
                user_vector = weighted_sum / norm
                return user_vector, interacted_vectors

        return None, interacted_vectors

    @classmethod
    def generate_explanation(cls, candidate, max_sim_info, top_category_name, is_user_cold_start=False):
        """
        Creates a natural, personalized explanation for why this item was recommended.
        Examples:
          - "Recommended because you like handmade pottery."
          - "Recommended because you purchased Ocean Wave Ceramic Mug."
          - "Recommended because you saved Leather Journal to your wishlist."
          - "Recommended because you recently explored Walnut Catch-All Tray."
          - "Trending bestseller loved by the craft community (⭐ 4.9)"
        """
        cat_name = candidate.category.name if candidate.category else 'Artisan Crafts'
        cat_clean = cat_name.lower().replace('handmade', '').strip()

        if is_user_cold_start:
            # Fallback explanations for new users
            avg_rating = candidate.average_rating
            if avg_rating and avg_rating >= 4.5:
                return f"Top-rated handcrafted craft loved by the community (⭐ {avg_rating:.1f})"
            elif candidate.total_orders and candidate.total_orders > 2:
                return f"Trending bestseller in {cat_name}"
            else:
                return f"Curated handcrafted {cat_clean or cat_name.lower()} pick for new craft lovers"

        # If we found a closely related product in user history
        if max_sim_info:
            sim, ref_prod, ref_source = max_sim_info
            if sim >= 0.55:
                prod_title = ref_prod.name
                if len(prod_title) > 32:
                    prod_title = prod_title[:29] + '...'

                if ref_source == 'purchase':
                    return f"Recommended because you bought '{prod_title}'"
                elif ref_source == 'wishlist':
                    return f"Recommended because you saved '{prod_title}' to your wishlist"
                elif ref_source == 'browsing':
                    return f"Recommended because you recently explored '{prod_title}'"
                elif ref_source == 'cart':
                    return f"Recommended because you added '{prod_title}' to your cart"

        # Category interest explanation
        if top_category_name and candidate.category and candidate.category.name.lower() == top_category_name.lower():
            if 'pottery' in top_category_name.lower():
                return "Recommended because you like handmade pottery."
            elif 'leather' in top_category_name.lower():
                return "Recommended because you like handcrafted leather goods."
            elif 'wood' in top_category_name.lower():
                return "Recommended because you like handmade woodwork."
            else:
                return f"Recommended because you like handmade {cat_clean or top_category_name.lower()}."

        if candidate.category:
            return f"Curated artisan pick in {cat_name} tailored to your taste."

        return "Curated to match your unique artisan aesthetic and preferences."

    @classmethod
    def get_fallback_recommendations(cls, limit=12, exclude_ids=None):
        """
        Intelligent fallback recommendations for new users:
        - Combines top-rated products, trending bestsellers, and category diversity.
        - Attaches meaningful fallback explanations.
        """
        exclude_ids = exclude_ids or set()
        candidates = Product.objects.filter(is_active=True).exclude(id__in=exclude_ids).select_related(
            'category', 'seller'
        ).annotate(
            avg_rating=Avg('reviews__rating'),
            order_count=Count('orders')
        ).order_by('-avg_rating', '-order_count', '-created_at')

        results = []
        seen_categories = set()
        deferred = []

        # Ensure category diversity in first few slots
        for p in candidates:
            cat_id = p.category_id
            p.recommendation_reason = cls.generate_explanation(p, None, None, is_user_cold_start=True)
            if cat_id not in seen_categories:
                seen_categories.add(cat_id)
                results.append(p)
            else:
                deferred.append(p)

            if len(results) >= limit:
                break

        # Fill remaining if needed
        if len(results) < limit:
            for p in deferred:
                if p not in results:
                    results.append(p)
                if len(results) >= limit:
                    break

        return results[:limit]

    @classmethod
    def get_personalized_recommendations(cls, user, limit=12):
        """
        Main recommendation entrypoint:
        1. Gathers user interactions (orders, wishlist, cart, browsing, category affinity).
        2. If user is brand new (cold-start), returns smart diverse fallback recommendations with reasons.
        3. Computes normalized taste vector from product embeddings.
        4. Calculates semantic similarity + category boost + quality ranking.
        5. Assigns personalized explanation to each product.
        """
        interactions, purchased_ids, category_scores = cls.get_user_interactions(user)

        # Cold-start check: If user has zero interaction history
        if not interactions and not category_scores:
            return cls.get_fallback_recommendations(limit=limit)

        user_vector, interacted_vectors = cls.compute_user_taste_vector(interactions)

        # Normalize category affinities so max is 1.0
        max_cat_score = max(category_scores.values()) if category_scores else 1.0
        normalized_cat_scores = {cid: score / max_cat_score for cid, score in category_scores.items()}

        # Identify user's top category name
        top_category_name = None
        if category_scores:
            top_cat_id = max(category_scores, key=category_scores.get)
            try:
                top_category_name = Category.objects.get(id=top_cat_id).name
            except Category.DoesNotExist:
                pass

        # Candidate pool: active products, excluding already purchased products
        candidates_qs = Product.objects.filter(is_active=True).select_related(
            'category', 'seller'
        ).annotate(
            annotated_rating=Avg('reviews__rating'),
            annotated_orders=Count('orders')
        )

        # Prefer excluding purchased items so user gets fresh discoveries
        candidates = list(candidates_qs.exclude(id__in=purchased_ids))
        if len(candidates) < 4:
            # If catalog is very small, fall back to including all active products
            candidates = list(candidates_qs)

        # Preload embeddings for candidate products
        candidate_ids = [c.id for c in candidates]
        candidate_embeddings = {
            emb.product_id: np.array(emb.vector, dtype=np.float32)
            for emb in ProductEmbedding.objects.filter(product_id__in=candidate_ids)
            if emb.vector
        }

        now = timezone.now()
        scored_candidates = []

        for candidate in candidates:
            cand_vec = candidate_embeddings.get(candidate.id)

            # 1. Semantic Similarity Score (0.0 to 1.0)
            semantic_score = 0.0
            best_ref_match = None  # (similarity, ref_product, ref_source)

            if cand_vec is not None:
                if user_vector is not None:
                    semantic_score = cosine_similarity_vec(user_vector, cand_vec)

                # Check individual similarities against specific user items for explanations
                for pid, (ref_v, ref_p, ref_src) in interacted_vectors.items():
                    if pid == candidate.id:
                        continue
                    sim = cosine_similarity_vec(ref_v, cand_vec)
                    if best_ref_match is None or sim > best_ref_match[0]:
                        best_ref_match = (sim, ref_p, ref_src)

            # 2. Category Affinity Score (0.0 to 1.0)
            cat_affinity = normalized_cat_scores.get(candidate.category_id, 0.0)

            # 3. Product Popularity / Quality (0.0 to 1.0)
            rating_val = candidate.annotated_rating or candidate.average_rating or 4.0
            rating_norm = min(1.0, rating_val / 5.0)
            order_count = candidate.annotated_orders or candidate.total_orders or 0
            order_norm = min(1.0, math.log1p(order_count) / math.log1p(15))
            quality_score = 0.6 * rating_norm + 0.4 * order_norm

            # 4. Freshness bonus for recent items (up to 0.08)
            days_old = (now - candidate.created_at).days if candidate.created_at else 30
            freshness_bonus = max(0.0, (30 - min(30, days_old)) / 30.0) * 0.08

            # Composite Personalized Score:
            # 45% Semantic Similarity, 30% Category Affinity, 20% Quality, 5% Freshness
            composite_score = (
                0.45 * semantic_score +
                0.30 * cat_affinity +
                0.20 * quality_score +
                freshness_bonus
            )

            # Penalty if candidate is already in wishlist or cart (we want new discoveries first)
            if candidate.id in interactions:
                if interactions[candidate.id]['source'] in ('wishlist', 'cart'):
                    composite_score *= 0.85

            # Dynamic human-readable explanation
            explanation = cls.generate_explanation(
                candidate,
                best_ref_match,
                top_category_name,
                is_user_cold_start=False
            )
            candidate.recommendation_reason = explanation
            candidate.ai_relevance_score = round(composite_score * 100, 1)

            scored_candidates.append((composite_score, candidate))

        # Sort descending by composite score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        ranked_products = [item[1] for item in scored_candidates]

        # If user had interactions but ranked list is short, top up with fallback
        if len(ranked_products) < limit:
            existing_ids = {p.id for p in ranked_products}
            fallback_items = cls.get_fallback_recommendations(limit=limit, exclude_ids=existing_ids | purchased_ids)
            for fb in fallback_items:
                ranked_products.append(fb)
                if len(ranked_products) >= limit:
                    break

        return ranked_products[:limit]
