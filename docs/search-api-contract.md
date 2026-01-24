# Search API Contract

## API Endpoints

### 1. Universal Search Endpoint

**`GET /api/search`**

Universal search across multiple entity types with unified response format.

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `q` | string | Yes | - | Search query (min: 1, max: 500 chars) |
| `entities` | string[] | No | `["products"]` | Entity types to search: `products`, `alerts`, `categories`, `scan_jobs` |
| `store` | string[] | No | - | Filter by stores (multi-select) |
| `date_from` | date | No | - | Filter by creation date (ISO 8601) |
| `date_to` | date | No | - | Filter by creation date (ISO 8601) |
| `active_only` | boolean | No | `false` | Show only active/enabled items |
| `sort_by` | string | No | `relevance` | Sort field: `relevance`, `created_at`, `name`, `price` |
| `sort_order` | string | No | `desc` | Sort order: `asc`, `desc` |
| `cursor` | string | No | - | Cursor for pagination |
| `limit` | integer | No | `20` | Results per page (max: 100) |

#### Response Schema

```json
{
  "results": [
    {
      "id": "string",
      "type": "products|alerts|categories|scan_jobs",
      "score": "number (0-1)",
      "data": {
        // Entity-specific data structure
      },
      "highlights": {
        "field_name": ["<mark>highlighted</mark> text"]
      },
      "url": "string", // Direct link to item
      "created_at": "string (ISO 8601)",
      "updated_at": "string (ISO 8601)"
    }
  ],
  "pagination": {
    "total_count": "number|null", // Expensive, only calculated if < 10k results
    "has_next": "boolean",
    "has_previous": "boolean", 
    "next_cursor": "string|null",
    "previous_cursor": "string|null",
    "limit": "number"
  },
  "facets": {
    "stores": [
      {"name": "amazon_us", "count": 123, "display_name": "Amazon"}
    ],
    "entity_types": [
      {"name": "products", "count": 456}
    ],
    "date_ranges": [
      {"name": "last_week", "count": 78}
    ]
  },
  "query_info": {
    "query": "string",
    "processed_query": "string", // Cleaned/normalized query
    "response_time_ms": "number",
    "total_results": "number"
  }
}
```

### 2. Product-Specific Search

**`GET /api/products/search`**

Dedicated product search with product-specific filters and optimization.

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `q` | string | No | - | Full-text search query |
| `sku` | string | No | - | SKU/ASIN exact or partial match |
| `title` | string | No | - | Title contains text (ILIKE) |
| `store` | string[] | No | - | Filter by stores |
| `price_min` | number | No | - | Minimum price (current or MSRP) |
| `price_max` | number | No | - | Maximum price (current or MSRP) |
| `discount_min` | number | No | - | Minimum discount percentage |
| `has_alerts` | boolean | No | - | Has price alerts triggered |
| `in_stock` | boolean | No | - | Currently in stock (latest price history) |
| `created_after` | date | No | - | Created after date |
| `created_before` | date | No | - | Created before date |
| `sort_by` | string | No | `relevance` | `relevance`, `created_at`, `title`, `price`, `discount` |
| `sort_order` | string | No | `desc` | `asc`, `desc` |
| `cursor` | string | No | - | Pagination cursor |
| `limit` | integer | No | `20` | Results per page (1-100) |
| `include_history` | boolean | No | `false` | Include recent price history |
| `include_alerts` | boolean | No | `false` | Include recent alerts |

#### Response Schema

```json
{
  "products": [
    {
      "id": "number",
      "sku": "string",
      "store": "string",
      "title": "string",
      "url": "string|null",
      "image_url": "string|null", 
      "msrp": "number|null",
      "baseline_price": "number|null",
      "current_price": "number|null", // From latest price history
      "price_change": "number|null", // Percentage change
      "discount_percent": "number|null",
      "in_stock": "boolean",
      "created_at": "string",
      "search_score": "number",
      "highlights": {
        "title": ["<mark>iPhone</mark> 14 Pro"],
        "sku": ["B08<mark>N5W</mark>RWNW"]
      },
      "recent_history": [ // If include_history=true
        {
          "price": "number",
          "fetched_at": "string",
          "availability": "string"
        }
      ],
      "recent_alerts": [ // If include_alerts=true
        {
          "triggered_price": "number", 
          "discount_percent": "number",
          "sent_at": "string"
        }
      ]
    }
  ],
  "pagination": { /* Same as universal search */ },
  "facets": {
    "stores": [{"name": "amazon_us", "count": 45, "display_name": "Amazon"}],
    "price_ranges": [
      {"min": 0, "max": 100, "count": 23},
      {"min": 100, "max": 500, "count": 67}
    ],
    "availability": [
      {"name": "in_stock", "count": 89},
      {"name": "out_of_stock", "count": 12}
    ]
  },
  "statistics": {
    "total_products": "number",
    "avg_price": "number",
    "avg_discount": "number",
    "top_stores": ["amazon_us", "walmart"]
  }
}
```

### 3. Alert Search

**`GET /api/alerts/search`**

Search price alerts with alert-specific filters.

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `q` | string | No | - | Search in product title/SKU |
| `store` | string[] | No | - | Filter by product stores |
| `price_min` | number | No | - | Minimum triggered price |
| `price_max` | number | No | - | Maximum triggered price |
| `discount_min` | number | No | - | Minimum discount percentage |
| `discount_max` | number | No | - | Maximum discount percentage |
| `rule_type` | string[] | No | - | Filter by rule types |
| `sent_after` | date | No | - | Sent after date |
| `sent_before` | date | No | - | Sent before date |
| `has_message_id` | boolean | No | - | Has Discord message ID |
| `sort_by` | string | No | `sent_at` | `sent_at`, `discount_percent`, `price_drop` |
| `sort_order` | string | No | `desc` | `asc`, `desc` |
| `cursor` | string | No | - | Pagination cursor |
| `limit` | integer | No | `20` | Results per page |

### 4. Category Search

**`GET /api/categories/search`**

Search store categories with category-specific filters.

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `q` | string | No | - | Search category name/keywords |
| `store` | string[] | No | - | Filter by stores |
| `enabled` | boolean | No | - | Filter by enabled status |
| `priority_min` | integer | No | - | Minimum priority (1-10) |
| `priority_max` | integer | No | - | Maximum priority (1-10) |
| `performance` | string | No | - | `high`, `medium`, `low` (deals/products ratio) |
| `last_scanned_after` | date | No | - | Last scanned after date |
| `has_errors` | boolean | No | - | Has recent errors |
| `sort_by` | string | No | `priority` | `priority`, `performance`, `last_scanned` |
| `sort_order` | string | No | `desc` | `asc`, `desc` |
| `cursor` | string | No | - | Pagination cursor |
| `limit` | integer | No | `20` | Results per page |

### 5. Scan Job Search

**`GET /api/scans/search`**

Search scan job history with job-specific filters.

#### Query Parameters  

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `q` | string | No | - | Search in error messages |
| `status` | string[] | No | - | Job statuses: `pending`, `running`, `completed`, `failed` |
| `job_type` | string[] | No | - | Job types: `category`, `manual`, `scheduled` |
| `store` | string[] | No | - | Filter by store (via category) |
| `success_rate_min` | number | No | - | Minimum success rate (0-100) |
| `duration_min` | integer | No | - | Minimum duration in seconds |
| `duration_max` | integer | No | - | Maximum duration in seconds |
| `created_after` | date | No | - | Created after date |
| `created_before` | date | No | - | Created before date |
| `sort_by` | string | No | `created_at` | `created_at`, `duration`, `success_rate` |
| `sort_order` | string | No | `desc` | `asc`, `desc` |
| `cursor` | string | No | - | Pagination cursor |
| `limit` | integer | No | `20` | Results per page |

### 6. Search Suggestions/Autocomplete

**`GET /api/search/suggestions`**

Get search suggestions and autocomplete data.

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `q` | string | Yes | - | Partial query (min: 2 chars) |
| `entity_type` | string | No | `products` | Entity type for suggestions |
| `field` | string | No | - | Specific field: `title`, `sku`, `store`, `category` |
| `limit` | integer | No | `10` | Max suggestions (1-20) |

#### Response Schema

```json
{
  "suggestions": [
    {
      "text": "iPhone 14 Pro",
      "type": "product_title", 
      "count": 15, // How many results this would return
      "highlight": "<mark>iPhone</mark> 14 Pro"
    },
    {
      "text": "B08N5WRWNW",
      "type": "product_sku",
      "count": 1,
      "highlight": "B08<mark>N5W</mark>RWNW"  
    }
  ],
  "recent_searches": [
    {"query": "macbook pro", "timestamp": "2023-01-15T10:30:00Z"},
    {"query": "nintendo switch", "timestamp": "2023-01-14T15:45:00Z"}
  ],
  "popular_searches": [
    {"query": "iphone", "count": 1250},
    {"query": "laptop deals", "count": 890}
  ]
}
```

### 7. Search Analytics

**`GET /api/search/analytics`**

Get search usage analytics (admin endpoint).

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `date_from` | date | No | 30 days ago | Analytics date range start |
| `date_to` | date | No | today | Analytics date range end |
| `breakdown` | string | No | `daily` | `hourly`, `daily`, `weekly` |

#### Response Schema

```json
{
  "summary": {
    "total_searches": "number",
    "unique_queries": "number", 
    "avg_response_time": "number",
    "success_rate": "number"
  },
  "timeline": [
    {
      "date": "2023-01-15",
      "searches": 245,
      "avg_response_time": 150,
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

## Common Response Patterns

### Error Responses

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

### Search Highlights

Search results include highlights showing matched terms:

```json
{
  "highlights": {
    "title": ["<mark>iPhone</mark> 14 Pro Max 256GB"],
    "sku": ["B08<mark>N5W</mark>RWNW"],
    "description": ["Latest <mark>iPhone</mark> with advanced camera"]
  }
}
```

### Cursor Pagination

Cursors are base64-encoded JSON containing:

```json
{
  "sort_field": "created_at",
  "sort_value": "2023-01-15T10:30:00Z", 
  "id": 12345,
  "direction": "next"
}
```

## OpenAPI Schema Extensions

All search endpoints include these OpenAPI extensions:

```yaml
paths:
  /api/search:
    get:
      tags: [Search]
      summary: Universal search across entities
      description: |
        Search across products, alerts, categories, and scan jobs with unified response format.
        Supports full-text search, filtering, sorting, and cursor-based pagination.
      parameters:
        - name: q
          in: query
          required: true
          schema:
            type: string
            minLength: 1
            maxLength: 500
            example: "iphone 14 pro"
          description: Search query with optional syntax (quotes, field:value, etc.)
      responses:
        '200':
          description: Search results
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UniversalSearchResponse'
        '400':
          description: Invalid search parameters
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
        '429':
          description: Rate limit exceeded
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/ErrorResponse'
      x-code-samples:
        - lang: curl
          source: |
            curl -X GET "http://localhost:8001/api/search?q=iphone&entities=products&limit=20"
        - lang: python  
          source: |
            response = requests.get("http://localhost:8001/api/search", {
                "q": "iphone",
                "entities": ["products"],
                "limit": 20
            })
```

## Rate Limiting

All search endpoints are rate limited:

- **Authenticated users**: 100 requests/minute
- **Unauthenticated**: 20 requests/minute  
- **Burst allowance**: 10 requests above limit
- **Rate limit headers**: Include remaining requests and reset time

## Caching Strategy

Search responses are cached based on:

- **Query hash**: MD5 of normalized query + filters
- **TTL**: 300 seconds (5 minutes) for stable results
- **Invalidation**: On data updates affecting result set
- **Cache headers**: Include cache status and TTL in response