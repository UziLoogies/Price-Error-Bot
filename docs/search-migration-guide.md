# Search Enhancement Migration Guide

This guide helps you upgrade from the basic filtering to the new enhanced search functionality in Price Error Bot.

## What's New

### Enhanced Search Features
- **Full-text search** with PostgreSQL tsvector/tsquery
- **Advanced filtering** with multiple filter combinations
- **Relevance ranking** for better result ordering
- **Search suggestions** and auto-complete
- **Faceted search** with result counts
- **Performance optimizations** with database indexes
- **Search analytics** for usage monitoring

### New API Endpoints
- `GET /api/search/products` - Advanced product search
- `GET /api/search/alerts` - Alert search with filters
- `GET /api/search/suggestions` - Auto-complete suggestions
- `GET /api/search/universal` - Cross-entity search

### UI Improvements
- New "Search Products" tab in dashboard
- Advanced filter panel with collapsible sections
- Search suggestions dropdown
- Improved result display with highlighting
- Better pagination controls

## Migration Steps

### 1. Database Migration

**Automatic Migration:**
```bash
# Activate virtual environment
source venv/bin/activate  # Linux/macOS
# .\venv\Scripts\Activate.ps1  # Windows

# Run the search enhancement migration
alembic upgrade head
```

**What This Does:**
- Enables PostgreSQL extensions: `pg_trgm`, `btree_gin`
- Adds `search_vector` columns to `products` and `store_categories`
- Creates GIN indexes for full-text search
- Creates trigram indexes for fuzzy matching
- Creates composite indexes for common queries
- Adds search analytics tables
- Creates triggers for automatic search vector updates

**Manual Verification:**
```sql
-- Connect to database
docker exec -it price_bot_postgres psql -U price_bot -d price_bot

-- Verify extensions
\dx

-- Verify indexes exist
\d+ products
\d+ store_categories

-- Test full-text search works
SELECT title, sku FROM products WHERE search_vector @@ to_tsquery('electronics');
```

### 2. Seed Test Data (Optional)

To test the search functionality with realistic data:

```bash
# Create comprehensive test data
python scripts/seed_search_data.py

# View statistics
python scripts/seed_search_data.py --stats

# Clear test data (if needed)
python scripts/seed_search_data.py --clear
```

### 3. Update Application Dependencies

The new search functionality uses existing dependencies, but verify they're up to date:

```bash
# Update dependencies
pip install -e . --upgrade

# Verify search endpoints work
curl "http://localhost:8001/api/search/products?q=test&limit=5"
```

## Breaking Changes

### API Changes
- **None**: All existing API endpoints remain unchanged
- **New endpoints**: Additional search endpoints are added
- **Backward compatibility**: Existing filtering continues to work

### Database Changes
- **New columns**: `search_vector` added (nullable, doesn't affect existing queries)
- **New tables**: `search_queries`, `search_suggestions` (independent)
- **New indexes**: Improve performance, don't affect existing functionality

### UI Changes
- **Existing tabs**: All current tabs unchanged
- **New tab**: "Search Products" tab added
- **Client-side filtering**: Still works as fallback

## Post-Migration Validation

### 1. Verify Search Functionality

**Test Basic Search:**
```bash
# Test product search
curl "http://localhost:8001/api/search/products?q=electronics&limit=5"

# Test suggestions
curl "http://localhost:8001/api/search/suggestions?q=elec&entity_type=products"

# Test alerts search
curl "http://localhost:8001/api/search/alerts?q=&limit=5"
```

**Expected Response:**
```json
{
  "products": [...],
  "pagination": {
    "has_next": false,
    "has_previous": false,
    "limit": 5
  },
  "facets": {
    "stores": [...]
  },
  "query_info": {
    "query": "electronics",
    "response_time_ms": 150,
    "total_results": 5
  }
}
```

### 2. Test UI Components

1. **Open dashboard**: http://localhost:8001
2. **Navigate** to "Search Products" tab
3. **Enter search query**: Try "electronics" or product names
4. **Test filters**: Apply store and price filters
5. **Test sorting**: Change sort options
6. **Test suggestions**: Type partial queries and verify dropdown

### 3. Performance Validation

**Check Query Performance:**
```sql
-- Test search query performance
EXPLAIN ANALYZE 
SELECT * FROM products 
WHERE search_vector @@ to_tsquery('electronics:*') 
LIMIT 20;

-- Should show "Bitmap Index Scan" or "Index Scan"
-- Execution time should be < 100ms for typical queries
```

**Monitor Response Times:**
```bash
# Test API response times
time curl "http://localhost:8001/api/search/products?q=electronics"

# Should complete in < 500ms
```

## Rollback Plan

If you encounter issues, you can rollback the changes:

### 1. Rollback Database Migration

```bash
# Rollback to previous migration
alembic downgrade -1

# Or rollback to specific revision
alembic downgrade 36c4b2d3a9f0  # Previous revision before search
```

### 2. Remove Search Components

```bash
# Remove search-related files
rm -f src/search/__init__.py
rm -f src/search/query_builder.py
rm -f src/search/service.py
rm -f src/api/routes/search.py

# Remove test files
rm -f tests/test_search_integration.py
rm -f tests/test_search_performance.py
```

### 3. Revert Main App Changes

```bash
# Revert src/main.py to remove search router
git checkout HEAD~1 -- src/main.py

# Revert dashboard.html if needed
git checkout HEAD~1 -- src/templates/dashboard.html
```

### 4. Restart Application

```bash
# Restart with reverted changes
./start.sh  # Linux/macOS
# .\start.ps1  # Windows
```

## Troubleshooting Migration Issues

### Migration Fails with Extension Error

**Error:** `extension "pg_trgm" does not exist`

**Solution:**
```bash
# Connect to PostgreSQL as superuser
docker exec -it price_bot_postgres psql -U postgres

# Install extensions manually
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;

# Then retry migration
alembic upgrade head
```

### Migration Fails with Permission Error

**Error:** `permission denied to create extension`

**Solution:**
```bash
# Restart PostgreSQL container with superuser
docker compose down postgres
docker compose up -d postgres

# Wait for container to be ready, then retry migration
alembic upgrade head
```

### Search Vectors Not Populated

**Error:** Search returns no results even for existing products

**Solution:**
```sql
-- Connect to database
docker exec -it price_bot_postgres psql -U price_bot -d price_bot

-- Manually populate search vectors
UPDATE products SET search_vector = 
    setweight(to_tsvector('english', COALESCE(title, '')), 'A') ||
    setweight(to_tsvector('english', COALESCE(sku, '')), 'B') ||
    setweight(to_tsvector('english', COALESCE(store, '')), 'C')
WHERE search_vector IS NULL;

-- Verify population
SELECT COUNT(*) FROM products WHERE search_vector IS NOT NULL;
```

### API Endpoints Not Found

**Error:** 404 errors when accessing `/api/search/*` endpoints

**Solution:**
```bash
# Verify search router is included in main.py
grep -n "search.router" src/main.py

# Restart application
./start.sh  # Linux/macOS
# .\start.ps1  # Windows

# Test API is working
curl "http://localhost:8001/docs"  # Should show search endpoints
```

## Support

For additional help with the search migration:

1. **Check logs:** `logs/app.log` and `logs/error.log`
2. **Enable debug mode:** Set `LOG_LEVEL=DEBUG` in `.env`
3. **Verify database:** Check PostgreSQL container is healthy
4. **Test API directly:** Use curl or Postman to test endpoints
5. **Review documentation:** See `docs/search-user-guide.md` for usage help

## Performance Expectations

After migration, you should see:

- **Faster searches:** 200-500ms for complex queries (vs 2-5s client-side)
- **Better relevance:** Results ranked by match quality
- **More features:** Advanced filtering and suggestions
- **Scalability:** Handles 50,000+ products efficiently
- **Analytics:** Search usage tracking and optimization data

The enhanced search functionality significantly improves user experience while maintaining all existing features.