# Bug Fix: Affiliate Dropdown Not Populating

## Issue
The affiliate dropdowns in BOTH the "Fetch Data" and "Run Fraud Analysis" panels showed "No affiliates found" even when searching for specific affiliate codes.

## Root Cause
Both dropdowns were loading data from `/api/affiliates`, which returns affiliate statistics from the **fraud_results** table (analyzed data only). If no fraud analysis had been run yet, or if certain affiliates hadn't been analyzed, they wouldn't appear in the dropdowns.

## Solution
Created a new endpoint `/api/source-affiliates` that loads affiliates directly from the **source data tables** (free and paid), not from analyzed results. Updated BOTH dropdowns to use this new endpoint.

### Changes Made

#### 1. Backend - New API Endpoint
**File**: `dashboard/app.py`

Added `/api/source-affiliates` endpoint that:
- Queries `free` table for `site_code` (affiliate codes)
- Queries `paid` table for `proc_name` (processor/affiliate names)
- Combines and aggregates counts
- Returns all unique affiliate codes with account counts

```python
@app.route('/api/source-affiliates')
def api_source_affiliates():
    """Get affiliates from source data (free/paid tables) for filtering"""
    # Queries both free.site_code and paid.proc_name
    # Returns: [{"code": "affiliate1", "total_accounts": 150}, ...]
```

#### 2. Frontend - Updated Data Source (2 places)
**File**: `dashboard/templates/index.html`

**Changed `loadFetchFilters()`** - for "Fetch Data" panel:
```javascript
const affData = await api('/api/source-affiliates');  // Was: /api/affiliates
```

**Changed `loadAnalysisFilters()`** - for "Run Fraud Analysis" panel:
```javascript
const affData = await api('/api/source-affiliates');  // Was: /api/affiliates
```

#### 3. Added Debug Logging
Added console logging to help diagnose similar issues in the future:
- Logs when affiliate data is loaded
- Logs the count of affiliates found
- Logs filtering operations
- Logs search queries

## Testing

### How to Verify the Fix
1. **Restart the dashboard** (to load new endpoint)
2. **Open browser console** (F12)
3. **Navigate to Reports tab** 
4. **Check console** - should see:
   ```
   Loaded source affiliates API response: {affiliates: Array(XX)}
   Loaded XX affiliates for analysis filters
   ```
5. **Test "Fetch Data" dropdown**:
   - Click "Select affiliates..." in Fetch Data panel
   - Should see full list of affiliates
6. **Test "Run Fraud Analysis" dropdown**:
   - Click "Select affiliates..." in Run Analysis panel
   - Should see full list of affiliates

### Expected Results
- ✅ Both dropdowns show all affiliates from your free/paid tables
- ✅ Search functionality works correctly in both
- ✅ Can select multiple affiliates in both panels
- ✅ Selected affiliates are used for filtering

## Related Files
- `dashboard/app.py` - New `/api/source-affiliates` endpoint
- `dashboard/templates/index.html` - Updated 2 functions (`loadFetchFilters` and `loadAnalysisFilters`)
- `database.py` - No changes (uses existing free/paid tables)

## Impact
- ✅ Fixes empty dropdown issue in BOTH panels
- ✅ Allows filtering by affiliates before running any analysis
- ✅ Shows accurate account counts from source data
- ✅ No breaking changes to existing functionality

## Notes
- The original `/api/affiliates` endpoint still exists and is used elsewhere (Affiliates tab, which shows fraud statistics)
- This fix affects BOTH the fetch and analysis filtering dropdowns
- The same pattern could be applied to campaigns if they have similar issues (though campaigns come from `/api/stats` which should work)

---

**Fix Date**: January 25, 2026
**Status**: ✅ READY FOR TESTING
**Affected Panels**: Fetch Data + Run Fraud Analysis
