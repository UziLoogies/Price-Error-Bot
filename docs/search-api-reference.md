# Search API Reference

Complete API reference for the enhanced search functionality in Price Error Bot.

## Overview

The search API provides powerful, fast, and flexible search across all entities in the Price Error Bot system. It supports:

- **Full-text search** with relevance ranking
- **Advanced filtering** with multiple criteria
- **Faceted search** with result counts
- **Auto-complete suggestions** 
- **Cursor-based pagination** for stability
- **Search analytics** for optimization

## Base URL

All search endpoints are under the `/api/search` prefix:

```
http://localhost:8001/api/search/
```

## Authentication

Search endpoints use the same authentication as other API endpoints. No special authentication is required for basic search functionality.

## Rate Limiting

Search endpoints are rate limited to prevent abuse:

- **60 requests per minute** per IP address
- **Burst allowance**: 10 additional requests
- **Rate limit headers** included in responses:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`

## Common Parameters

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Search query (1-500 characters) |
| `sort_by` | string | Sort field (varies by endpoint) |
| `sort_order` | string | `asc` or `desc` (default: `desc`) |
| `cursor` | string | Pagination cursor (opaque token) |
| `limit` | integer | Results per page (1-100, default: 20) |

### Filter Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `stores` | string[] | Filter by store codes |
| `date_from` | date | Start date (ISO 8601) |
| `date_to` | date | End date (ISO 8601) |
| `price_min` | number | Minimum price |
| `price_max` | number | Maximum price |

## Endpoints

### 1. Product Search

Search products with full-text search and advanced filtering.

```http
GET /api/search/products
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `q` | string | No | Search query (title, SKU, store) |
| `sku` | string | No | SKU exact or partial match |
| `title` | string | No | Title contains text (ILIKE) |
| `stores` | string[] | No | Filter by stores |
| `price_min` | number | No | Minimum price (≥ 0) |
| `price_max` | number | No | Maximum price (≥ 0) |
| `discount_min` | number | No | Minimum discount % (0-100) |
| `has_alerts` | boolean | No | Filter by alert existence |
| `in_stock` | boolean | No | Filter by stock status |
| `created_after` | datetime | No | Created after date |
| `created_before` | datetime | No | Created before date |
| `sort_by` | enum | No | `relevance`, `created_at`, `title`, `msrp`, `discount` |
| `sort_order` | enum | No | `asc`, `desc` |
| `cursor` | string | No | Pagination cursor |
| `limit` | integer | No | Results per page (1-100) |
| `include_history` | boolean | No | Include recent price history |
| `include_alerts` | boolean | No | Include recent alerts |

#### Response

```json
{
  "products": [
    {
      "id": 123,
      "sku": "B08N5WRWNW",
      "store": "amazon_us",
      "title": "Apple iPhone 13 Pro 256GB",
      "url": "https://amazon.com/dp/B08N5WRWNW",
      "image_url": "https://images.amazon.com/...",
      "msrp": 999.99,
      "baseline_price": 899.99,
      "current_price": 849.99,
      "discount_percent": 15.0,
      "in_stock": true,
      "created_at": "2023-01-15T10:30:00Z",
      "search_score": 0.95,
      "highlights": {
        "title": ["Apple <mark>iPhone</mark> 13 Pro 256GB"],
        "sku": ["B08N5<mark>WRW</mark>NW"]
      }
    }
  ],
  "pagination": {
    "has_next": true,
    "has_previous": false,
    "next_cursor": "eyJzb3J0X2ZpZWxkIjoi...",
    "limit": 20,
    "total_count": 1247
  },
  "facets": {
    "stores": [
      {"name": "amazon_us", "count": 456, "display_name": "Amazon"},
      {"name": "walmart", "count": 234, "display_name": "Walmart"}
    ],
    "price_ranges": [
      {"min": 0, "max": 100, "count": 89},
      {"min": 100, "max": 500, "count": 234}
    ]
  },
  "query_info": {
    "query": "iPhone Pro",
    "processed_query": "iphone & pro",
    "response_time_ms": 125,
    "total_results": 1247,
    "uses_fts": true
  }
}
```

#### Examples

```bash
# Basic search
curl "http://localhost:8001/api/search/products?q=iphone"

# Search with store filter
curl "http://localhost:8001/api/search/products?q=laptop&stores=amazon_us&stores=bestbuy"

# Price range search
curl "http://localhost:8001/api/search/products?q=electronics&price_min=100&price_max=500"

# Complex filtered search
curl "http://localhost:8001/api/search/products?q=gaming%20laptop&stores=amazon_us&price_min=800&discount_min=20&sort_by=discount&sort_order=desc"
```

### 2. Alert Search

Search price alerts with product information.

```http
GET /api/search/alerts
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `q` | string | No | Search in product title/SKU |
| `stores` | string[] | No | Filter by product stores |
| `price_min` | number | No | Minimum triggered price |
| `price_max` | number | No | Maximum triggered price |
| `discount_min` | number | No | Minimum discount % (0-100) |
| `discount_max` | number | No | Maximum discount % (0-100) |
| `rule_type` | string[] | No | Filter by rule types |
| `sent_after` | datetime | No | Sent after date |
| `sent_before` | datetime | No | Sent before date |
| `has_message_id` | boolean | No | Has Discord message ID |
| `sort_by` | enum | No | `sent_at`, `discount_percent`, `price_drop` |
| `sort_order` | enum | No | `asc`, `desc` |
| `cursor` | string | No | Pagination cursor |
| `limit` | integer | No | Results per page (1-100) |

#### Response

```json
{
  "alerts": [
    {
      "id": 456,
      "product_id": 123,
      "rule_id": 1,
      "triggered_price": 599.99,
      "previous_price": 999.99,
      "discount_percent": 40.0,
      "discord_message_id": "987654321098765432",
      "sent_at": "2023-01-15T14:30:00Z",
      "highlights": {
        "product_title": ["<mark>iPhone</mark> 13 Pro"]
      }
    }
  ],
  "pagination": { /* Same structure as products */ },
  "facets": {
    "stores": [...],
    "discount_ranges": [
      {"min": 0, "max": 25, "count": 45},
      {"min": 25, "max": 50, "count": 78}
    ]
  },
  "query_info": { /* Same structure as products */ }
}
```

### 3. Search Suggestions

Get auto-complete suggestions and search history.

```http
GET /api/search/suggestions
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `q` | string | Yes | Partial query (2-200 characters) |
| `entity_type` | enum | No | `products`, `alerts`, `categories` |
| `field` | string | No | Specific field (`title`, `sku`, `store`) |
| `limit` | integer | No | Max suggestions (1-20, default: 10) |

#### Response

```json
{
  "suggestions": [
    {
      "text": "iPhone 13 Pro Max",
      "type": "product_title",
      "count": 15,
      "highlight": "<mark>iPhone</mark> 13 Pro Max"
    },
    {
      "text": "B08N5WRWNW", 
      "type": "product_sku",
      "count": 1,
      "highlight": "B08<mark>N5W</mark>RWNW"
    }
  ],
  "recent_searches": [
    {
      "query": "macbook pro",
      "timestamp": "2023-01-15T10:30:00Z"
    }
  ],
  "popular_searches": [
    {"query": "iphone", "count": 1250},
    {"query": "laptop deals", "count": 890}
  ]
}
```

#### Examples

```bash
# Get product suggestions
curl "http://localhost:8001/api/search/suggestions?q=iPh&entity_type=products"

# Get SKU suggestions
curl "http://localhost:8001/api/search/suggestions?q=B08&entity_type=products&field=sku"

# Get category suggestions
curl "http://localhost:8001/api/search/suggestions?q=electronics&entity_type=categories"
```

### 4. Universal Search (Beta)

Search across multiple entity types with unified results.

```http
GET /api/search/universal
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `q` | string | Yes | Search query |
| `entities` | enum[] | No | Entity types: `products`, `alerts`, `categories` |
| `stores` | string[] | No | Filter by stores |
| `date_from` | datetime | No | Date range start |
| `date_to` | datetime | No | Date range end |
| `active_only` | boolean | No | Show only active items |
| `sort_by` | string | No | Sort field |
| `sort_order` | enum | No | `asc`, `desc` |
| `cursor` | string | No | Pagination cursor |
| `limit` | integer | No | Results per page |

### 5. Search Analytics (Admin)

Get search usage analytics and performance metrics.

```http
GET /api/search/analytics/summary
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `date_from` | date | No | Analytics start date |
| `date_to` | date | No | Analytics end date |
| `breakdown` | enum | No | `hourly`, `daily`, `weekly` |

#### Response

```json
{
  "summary": {
    "total_searches": 12450,
    "unique_queries": 3421,
    "avg_response_time": 187,
    "success_rate": 0.94
  },
  "timeline": [
    {
      "date": "2023-01-15",
      "searches": 245,
      "avg_response_time": 156,
      "zero_results": 12
    }
  ],
  "top_queries": [
    {"query": "iphone", "count": 89, "avg_results": 23},
    {"query": "laptop deals", "count": 67, "avg_results": 15}
  ],
  "performance_stats": {
    "p50_response_time": 120,
    "p95_response_time": 450,
    "p99_response_time": 800,
    "cache_hit_rate": 0.82
  }
}
```

## Error Handling

### Standard Error Response

```json
{
  "error": {
    "code": "SEARCH_QUERY_INVALID",
    "message": "Search query is too long (max 500 characters)",
    "details": {
      "field": "q",
      "provided_length": 523,
      "max_length": 500
    }
  }
}
```

### Common Error Codes

| Code | Status | Description |
|------|--------|-------------|
| `SEARCH_QUERY_INVALID` | 400 | Invalid search query |
| `SEARCH_QUERY_TOO_LONG` | 400 | Query exceeds 500 characters |
| `INVALID_FILTER_VALUE` | 400 | Filter parameter has invalid value |
| `SEARCH_TEMPORARILY_UNAVAILABLE` | 500 | Search service temporarily down |
| `DATABASE_CONNECTION_ERROR` | 500 | Database connectivity issues |

## Performance Guidelines

### Query Optimization

**Fast Queries (< 200ms):**
- Exact SKU matches
- Store-filtered searches
- Price range queries
- Recent date filters

**Moderate Queries (200-500ms):**
- Full-text searches
- Multi-filter combinations
- Sorted relevance results
- Large result sets (100+)

**Slower Queries (500ms+):**
- Very broad searches (no filters)
- Complex boolean queries
- Fuzzy matching on short terms
- Cross-entity universal search

### Best Practices

**DO:**
- Use specific search terms
- Apply relevant filters
- Limit result counts for UI
- Cache results when appropriate
- Use pagination for large sets

**DON'T:**
- Search without any filters
- Use very broad terms (< 3 characters)
- Request large result sets (> 100) 
- Make rapid sequential requests
- Search for common stop words

## Caching

Search results are automatically cached with Redis:

- **TTL**: 5 minutes for search results
- **TTL**: 1 hour for suggestions
- **Cache Key**: MD5 hash of query + filters
- **Cache Headers**: 
  - `X-Cache-Status`: `HIT`, `MISS`, `STALE`
  - `X-Cache-TTL`: Remaining cache time in seconds

## Monitoring

### Performance Metrics

Search performance is monitored with these metrics:

- **Response Time**: P50, P95, P99 percentiles
- **Query Volume**: Searches per minute/hour/day
- **Success Rate**: Percentage of successful searches
- **Cache Hit Rate**: Percentage of cached responses
- **Zero Results Rate**: Searches returning no results

### Health Checks

Monitor search health with:

```bash
# Test basic search functionality
curl "http://localhost:8001/api/search/products?q=test&limit=1"

# Check suggestions endpoint  
curl "http://localhost:8001/api/search/suggestions?q=test"

# Monitor response times
curl -w "@curl-format.txt" "http://localhost:8001/api/search/products?q=electronics"
```

### Troubleshooting

**Common Issues:**

1. **Slow Response Times**
   - Check database connections
   - Verify indexes exist and are used
   - Monitor query complexity
   - Check server load

2. **No Search Results**
   - Verify search indexes exist
   - Check search vectors are populated  
   - Test with exact SKU matches
   - Review filter combinations

3. **Search Errors**
   - Check PostgreSQL extensions installed
   - Verify database permissions
   - Review application logs
   - Test database connectivity

## Migration Notes

### Database Requirements

The search functionality requires:

- **PostgreSQL 12+** (for advanced full-text search)
- **Extensions**: `pg_trgm`, `btree_gin`
- **Search Indexes**: Created by migration 004_add_search_support
- **Search Vectors**: Auto-generated by triggers

### Upgrade Path

1. **Run Migration**: `alembic upgrade head`
2. **Verify Indexes**: Check database schema
3. **Test Functionality**: Use API endpoints
4. **Monitor Performance**: Check response times
5. **Populate Test Data**: Use seed scripts if needed

### Backward Compatibility

- All existing API endpoints remain unchanged
- Client-side filtering still works as fallback  
- No breaking changes to existing functionality
- New features are additive only

## SDK and Client Libraries

### Python Client Example

```python
import httpx

class SearchClient:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.AsyncClient()
    
    async def search_products(self, query: str, **filters):
        params = {"q": query, **filters}
        response = await self.client.get(f"{self.base_url}/api/search/products", params=params)
        return response.json()
    
    async def get_suggestions(self, query: str, entity_type: str = "products"):
        params = {"q": query, "entity_type": entity_type}
        response = await self.client.get(f"{self.base_url}/api/search/suggestions", params=params)
        return response.json()

# Usage
client = SearchClient("http://localhost:8001")
results = await client.search_products("iphone", stores=["amazon_us"], price_max=1000)
```

### JavaScript/Frontend Example

```javascript
class SearchAPI {
    constructor(baseUrl = '') {
        this.baseUrl = baseUrl;
    }
    
    async searchProducts(query, filters = {}) {
        const params = new URLSearchParams({ q: query, ...filters });
        const response = await fetch(`${this.baseUrl}/api/search/products?${params}`);
        return response.json();
    }
    
    async getSuggestions(query, entityType = 'products') {
        const params = new URLSearchParams({ q: query, entity_type: entityType });
        const response = await fetch(`${this.baseUrl}/api/search/suggestions?${params}`);
        return response.json();
    }
}

// Usage
const searchAPI = new SearchAPI();
const results = await searchAPI.searchProducts('iphone', { 
    stores: ['amazon_us'], 
    price_max: 1000 
});
```

## OpenAPI Schema

The complete OpenAPI schema is available at:
- **Interactive Docs**: http://localhost:8001/docs
- **OpenAPI JSON**: http://localhost:8001/openapi.json
- **ReDoc**: http://localhost:8001/redoc

All search endpoints include:
- Complete parameter documentation
- Response schema definitions
- Example requests and responses
- Error response formats

## Support

For API support and questions:

1. **Check Interactive Docs**: http://localhost:8001/docs
2. **Review Error Messages**: All errors include helpful details
3. **Enable Debug Logging**: Set `LOG_LEVEL=DEBUG` in `.env`
4. **Check Database**: Verify PostgreSQL container is healthy
5. **Test Direct Queries**: Use curl to isolate issues

The search API is designed to be developer-friendly with comprehensive documentation, clear error messages, and robust error handling.