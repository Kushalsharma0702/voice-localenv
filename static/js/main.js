// Global variables
        let customers = [];
        let filteredCustomers = [];
        let displayedCustomers = [];
        let selectedCustomers = new Set();
        let currentPage = 1;
        let recordsPerPage;
        
        // Batch upload pagination variables
        let batchCurrentPage = 1;
        let batchPageSize;  // Default to 20 per page
        let batchDateFilter = 'today';
        let selectedBatchIds = new Set();
        let ws = null;
        let refreshInterval = null;

        // Initialize dashboard
        document.addEventListener('DOMContentLoaded', function() {
            initializeWebSocket();
            initializeEventListeners();
            loadCustomerData();
            
            // Set default batch filter to today and page size to 20
            const batchSizeDropdown = document.getElementById('batchPageSize');
            document.getElementById('batchDateFilter').value = 'today';
            batchDateFilter = 'today';
            if (batchSizeDropdown) {
                batchSizeDropdown.value = '20';
                const selectedSize = batchSizeDropdown.value;
                batchPageSize = selectedSize === 'all' ? 'all' : parseInt(selectedSize, 10);
            }
            
            // Set default customer records per page to 20
            const recordsDropdown = document.getElementById('recordsPerPage');
            if (recordsDropdown) {
                recordsDropdown.value = '20';  // Set default to 20
                recordsPerPage = parseInt(recordsDropdown.value, 10);
                console.log('Initialized recordsPerPage dropdown to:', recordsDropdown.value);
                console.log('Set recordsPerPage variable to:', recordsPerPage);
            } else {
                console.error('Could not find recordsPerPage dropdown during initialization');
                recordsPerPage = 20;  // Fallback value
            }
            
            
            loadBatchDetails();
            loadCallStatuses();
            setupAutoRefresh();
        });

        // WebSocket connection
        function initializeWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws/dashboard/enhanced`;
            
            ws = new WebSocket(wsUrl);
            
            ws.onopen = function() {
                updateConnectionStatus('connected');
                logActivity('WebSocket connected successfully');
            };
            
            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                handleWebSocketMessage(data);
            };
            
            ws.onclose = function() {
                updateConnectionStatus('disconnected');
                logActivity('WebSocket disconnected, attempting to reconnect...');
                setTimeout(initializeWebSocket, 3000);
            };
            
            ws.onerror = function() {
                updateConnectionStatus('error');
                logActivity('WebSocket connection error');
            };
        }

        // Handle WebSocket messages
        function handleWebSocketMessage(data) {
            switch(data.event) {
                case 'call_status_update':
                    updateCustomerCallStatus(data.customer_id, data.status, data.message);
                    break;
                case 'upload_progress':
                    updateUploadProgress(data.progress, data.message);
                    break;
                case 'upload_complete':
                    // Refresh customer data when upload completes
                    logActivity('📊 Upload completed, refreshing customer data...');
                    setTimeout(() => loadCustomerData(true), 1000);
                    break;
                case 'bulk_operation_update':
                    updateBulkOperationStatus(data);
                    break;
                case 'data_update':
                    // Generic data update event
                    logActivity('📊 Data updated, refreshing customer list...');
                    loadCustomerData(false);
                    break;
                default:
                    console.log('Unknown WebSocket event:', data);
            }
        }

        // Initialize event listeners
        function initializeEventListeners() {
            // File upload
            const fileInput = document.getElementById('fileInput');
            const uploadArea = document.getElementById('uploadArea');
            
            fileInput.addEventListener('change', handleFileUpload);
            
            // Drag and drop
            uploadArea.addEventListener('dragover', function(e) {
                e.preventDefault();
                uploadArea.classList.add('dragover');
            });
            
            uploadArea.addEventListener('dragleave', function(e) {
                e.preventDefault();
                uploadArea.classList.remove('dragover');
            });
            
            uploadArea.addEventListener('drop', function(e) {
                e.preventDefault();
                uploadArea.classList.remove('dragover');
                if (e.dataTransfer.files.length > 0) {
                    fileInput.files = e.dataTransfer.files;
                    handleFileUpload();
                }
            });

            // Filter controls
            document.getElementById('searchInput').addEventListener('input', applyFilters);
            document.getElementById('uploadDateFilter').addEventListener('change', handleDateFilterChange);
            document.getElementById('callStatusFilter').addEventListener('change', applyFilters);
            document.getElementById('stateFilter').addEventListener('change', applyFilters);
            document.getElementById('clusterFilter').addEventListener('change', applyFilters);
            document.getElementById('branchFilter').addEventListener('change', applyFilters);
            document.getElementById('employeeFilter').addEventListener('change', applyFilters);
            document.getElementById('startDate').addEventListener('change', applyFilters);
            document.getElementById('endDate').addEventListener('change', applyFilters);

            // Bulk action buttons
            document.getElementById('refreshDataBtn').addEventListener('click', () => loadCustomerData(true));
            document.getElementById('selectAllFilteredBtn').addEventListener('click', selectAllFilteredCustomers);
            document.getElementById('callSelectedBtn').addEventListener('click', callSelectedCustomers);
            document.getElementById('updateSelectedStatusBtn').addEventListener('click', updateSelectedStatus);
            document.getElementById('exportSelectedBtn').addEventListener('click', exportSelectedCustomers);
            document.getElementById('clearFiltersBtn').addEventListener('click', clearAllFilters);

            // Pagination
            const recordsPerPageSelect = document.getElementById('recordsPerPage');
            if (recordsPerPageSelect) {
                console.log('Records per page dropdown found, initializing event listener');
                recordsPerPageSelect.addEventListener('change', function() {
                    console.log('=== PAGINATION CHANGE EVENT ===');
                    console.log('Dropdown value changed to:', this.value);
                    console.log('Type of this.value:', typeof this.value);
                    console.log('Previous recordsPerPage was:', recordsPerPage);
                    console.log('Type of previous recordsPerPage:', typeof recordsPerPage);
                    
                    // Add visual feedback
                    this.style.backgroundColor = '#e3f2fd';
                    setTimeout(() => {
                        this.style.backgroundColor = 'white';
                    }, 300);
                    
                    // Update recordsPerPage variable
                    if (this.value === 'all') {
                        recordsPerPage = 'all';
                    } else {
                        recordsPerPage = parseInt(this.value, 10);  // Use radix 10 for proper parsing
                    }
                    
                    console.log('New recordsPerPage set to:', recordsPerPage);
                    console.log('Type of new recordsPerPage:', typeof recordsPerPage);
                    
                    // Reset to first page
                    currentPage = 1;
                    console.log('currentPage reset to:', currentPage);
                    
                    // Re-render table with new pagination
                    console.log('About to call renderCustomerTable...');
                    renderCustomerTable();
                    
                    console.log('About to call updatePaginationInfo...');
                    updatePaginationInfo();
                    
                    // Show notification
                    showNotification(`Showing ${this.value === 'all' ? 'all' : this.value} records per page`, 'success');
                    console.log('=== PAGINATION CHANGE EVENT END ===');
                });
            } else {
                console.error('Records per page dropdown not found!');
            }
            
            document.getElementById('prevPageBtn').addEventListener('click', function() {
                if (currentPage > 1) {
                    currentPage--;
                    renderCustomerTable();
                }
            });
            
            document.getElementById('nextPageBtn').addEventListener('click', function() {
                if (recordsPerPage === 'all') {
                    return; // No pagination when showing all records
                }
                const totalPages = Math.ceil(filteredCustomers.length / recordsPerPage);
                if (currentPage < totalPages) {
                    currentPage++;
                    renderCustomerTable();
                }
            });

            // Select all checkbox
            document.getElementById('selectAll').addEventListener('change', function() {
                const checkboxes = document.querySelectorAll('#customerTableBody input[type="checkbox"]');
                checkboxes.forEach(cb => {
                    cb.checked = this.checked;
                    if (this.checked) {
                        selectedCustomers.add(cb.value);
                    } else {
                        selectedCustomers.delete(cb.value);
                    }
                });
                updateSelectionCount();
            });

            // Modal close
            document.getElementById('modalClose').addEventListener('click', function() {
                document.getElementById('customerModal').style.display = 'none';
            });

            // Batch upload controls
            document.getElementById('batchDateFilter').addEventListener('change', function() {
                batchDateFilter = this.value;
                batchCurrentPage = 1;
                loadBatchDetails();
            });

            document.getElementById('batchPageSize').addEventListener('change', function() {
                batchPageSize = this.value === 'all' ? 'all' : parseInt(this.value);
                batchCurrentPage = 1;
                loadBatchDetails();
            });

            document.getElementById('selectAllBatchBtn').addEventListener('click', selectAllFilteredUploads);

            document.getElementById('batchPrevBtn').addEventListener('click', function() {
                if (batchCurrentPage > 1) {
                    batchCurrentPage--;
                    loadBatchDetails();
                }
            });

            document.getElementById('batchNextBtn').addEventListener('click', function() {
                batchCurrentPage++;
                loadBatchDetails();
            });

            // Batch select all checkbox for current page
            document.getElementById('batchSelectAllPage').addEventListener('change', function() {
                const checkboxes = document.querySelectorAll('.batch-row-checkbox');
                checkboxes.forEach(cb => {
                    cb.checked = this.checked;
                    const batchId = cb.getAttribute('data-batch-id');
                    if (this.checked) {
                        selectedBatchIds.add(batchId);
                    } else {
                        selectedBatchIds.delete(batchId);
                    }
                });
                updateBatchSelectAllState();
            });

            // Individual batch row checkbox handlers (delegated)
            document.addEventListener('change', function(e) {
                if (e.target.classList.contains('batch-row-checkbox')) {
                    const batchId = e.target.getAttribute('data-batch-id');
                    if (e.target.checked) {
                        selectedBatchIds.add(batchId);
                    } else {
                        selectedBatchIds.delete(batchId);
                    }
                    updateBatchSelectAllState();
                }
            });
        }

        // Handle date filter changes
        function handleDateFilterChange() {
            const dateFilter = document.getElementById('uploadDateFilter').value;
            const customDateRange = document.getElementById('customDateRange');
            
            if (dateFilter === 'custom') {
                customDateRange.style.display = 'block';
            } else {
                customDateRange.style.display = 'none';
            }
            
            applyFilters();
        }

        // Load customer data from database with enhanced error handling
        async function loadCustomerData(forceRefresh = false) {
            try {
                showLoading(true);
                
                if (forceRefresh) {
                    logActivity('🔄 Force refreshing customer data from database...');
                } else {
                    logActivity('📊 Loading customer data from database...');
                }
                
                // Add cache-busting parameter to ensure fresh data
                const cacheBuster = `?_t=${Date.now()}`;
                const response = await fetch(`/api/customers${cacheBuster}`, {
                    method: 'GET',
                    headers: {
                        'Accept': 'application/json',
                        'Cache-Control': 'no-cache, no-store, must-revalidate',
                        'Pragma': 'no-cache',
                        'Expires': '0'
                    }
                });
                
                if (!response.ok) {
                    throw new Error(`Failed to fetch customers: ${response.status} ${response.statusText}`);
                }
                
                const responseData = await response.json();
                
                // Ensure we have an array of customers
                if (!Array.isArray(responseData)) {
                    throw new Error('Invalid response format: expected array of customers');
                }
                
                customers = responseData;
                filteredCustomers = [...customers];
                
                // Clear any existing selections since data has been refreshed
                selectedCustomers.clear();
                updateSelectionCount();
                
                populateFilterOptions();
                applyFilters();
                updatePaginationInfo();
                updateStatistics();
                
                const timestamp = getCurrentISTTime();
                logActivity(`✅ Successfully loaded ${customers.length} customers from database at ${timestamp} IST`);
                
                // Show success toast for manual refreshes
                if (forceRefresh) {
                    showToast(`Data refreshed: ${customers.length} customers loaded`, 'success');
                }
                
                // Update last refresh time in header
                document.getElementById('lastStatusUpdate').textContent = `Last update: ${timestamp} IST`;
                
                // Ensure pagination is properly set up after data load
                setTimeout(() => {
                    updatePaginationInfo();
                    console.log('Post-load pagination info updated');
                }, 100);
                
            } catch (error) {
                console.error('Error loading customers:', error);
                const errorMessage = `Failed to load customer data: ${error.message}`;
                logActivity(`❌ ${errorMessage}`, 'error');
                showToast(errorMessage, 'error');
                
                // Show error in table if no data is available
                if (customers.length === 0) {
                    const tbody = document.getElementById('customerTableBody');
                    tbody.innerHTML = `
                        <tr>
                            <td colspan="19" style="text-align: center; padding: 40px; color: #dc3545;">
                                <div style="margin-bottom: 10px;">⚠️ Error loading customer data</div>
                                <div style="font-size: 0.9em;">${error.message}</div>
                                <button class="bulk-btn bulk-btn-primary" onclick="loadCustomerData(true)" style="margin-top: 15px;">
                                    🔄 Retry
                                </button>
                            </td>
                        </tr>
                    `;
                }
            } finally {
                showLoading(false);
            }
        }

        // Load batch details from database
        async function loadBatchDetails() {
            try {
                logActivity('📊 Loading batch upload details...');
                
                // Build query parameters
                const params = new URLSearchParams({
                    page: batchCurrentPage,
                    page_size: batchPageSize === 'all' ? 1000 : batchPageSize  // Use large number for "all"
                });
                
                if (batchDateFilter) {
                    params.append('date_filter', batchDateFilter);
                }
                
                const response = await fetch(`/api/uploaded-files?${params}`, {
                    method: 'GET',
                    headers: {
                        'Accept': 'application/json',
                        'Cache-Control': 'no-cache'
                    }
                });
                
                if (!response.ok) {
                    throw new Error(`Failed to fetch batch data: ${response.status} ${response.statusText}`);
                }
                
                const responseData = await response.json();
                
                if (!responseData.success) {
                    throw new Error(responseData.error || 'Failed to load batch data');
                }
                
                const batches = responseData.uploads || [];
                const pagination = responseData.pagination || {};
                
                // Update batch statistics
                updateBatchStatistics(batches, pagination);
                
                // Populate batch table
                populateBatchTable(batches);
                
                // Update pagination controls
                updateBatchPagination(pagination);
                
                logActivity(`✅ Successfully loaded ${batches.length} batch uploads (page ${pagination.current_page} of ${pagination.total_pages})`);
                
            } catch (error) {
                console.error('Error loading batch details:', error);
                logActivity(`❌ Failed to load batch details: ${error.message}`, 'error');
                
                // Show error in batch table
                const tbody = document.getElementById('batchTableBody');
                tbody.innerHTML = `
                    <tr>
                        <td colspan="8" style="text-align: center; padding: 20px; color: #dc3545;">
                            <div>⚠️ Error loading batch data: ${error.message}</div>
                            <button class="refresh-batch-btn" onclick="loadBatchDetails()" style="margin-top: 10px;">
                                🔄 Retry
                            </button>
                        </td>
                    </tr>
                `;
            }
        }

        // Update batch statistics
        function updateBatchStatistics(batches, pagination) {
            const today = new Date().toDateString();
            
            // Calculate statistics from current page
            const totalBatches = pagination.total_count || 0;
            const todayBatches = batches.filter(batch => {
                const batchDate = new Date(batch.uploaded_at).toDateString();
                return batchDate === today;
            }).length;
            
            const totalRecords = batches.reduce((sum, batch) => sum + (batch.total_records || 0), 0);
            const totalSuccess = batches.reduce((sum, batch) => sum + (batch.success_records || 0), 0);
            const successRate = totalRecords > 0 ? Math.round((totalSuccess / totalRecords) * 100) : 0;
            
            // Update DOM elements
            document.getElementById('totalBatchesStat').textContent = totalBatches;
            document.getElementById('todayBatchesStat').textContent = todayBatches;
            document.getElementById('totalRecordsStat').textContent = totalRecords.toLocaleString();
            document.getElementById('successRateStat').textContent = `${successRate}%`;
        }

        // Populate batch table
        function populateBatchTable(batches) {
            const tbody = document.getElementById('batchTableBody');
            
            if (batches.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="8" style="text-align: center; padding: 20px; color: #666;">
                            📄 No batch uploads found
                        </td>
                    </tr>
                `;
                return;
            }
            
            const batchRows = batches.map(batch => {
                const uploadDate = new Date(batch.uploaded_at);
                const formattedDate = uploadDate.toLocaleDateString('en-IN', {
                    day: '2-digit',
                    month: 'short',
                    year: 'numeric',
                    hour: '2-digit',
                    minute: '2-digit'
                });
                
                const successRate = batch.total_records > 0 
                    ? Math.round((batch.success_records / batch.total_records) * 100)
                    : 0;
                
                const successRateClass = successRate >= 90 ? 'high' : 
                                       successRate >= 70 ? 'medium' : 'low';
                
                const statusClass = batch.status.toLowerCase().replace(' ', '-');
                const isSelected = selectedBatchIds.has(batch.id);
                
                return `
                    <tr data-batch-id="${batch.id}">
                        <td>
                            <input type="checkbox" class="batch-row-checkbox" 
                                   data-batch-id="${batch.id}" 
                                   ${isSelected ? 'checked' : ''}>
                        </td>
                        <td title="${batch.original_filename || batch.filename}">
                            ${truncateText(batch.original_filename || batch.filename, 25)}
                        </td>
                        <td>${formattedDate}</td>
                        <td>${batch.total_records.toLocaleString()}</td>
                        <td>
                            <span class="batch-success-rate ${successRateClass}">
                                ${successRate}% (${batch.success_records}/${batch.total_records})
                            </span>
                        </td>
                        <td>
                            <span class="batch-status ${statusClass}">
                                ${batch.status}
                            </span>
                        </td>
                        <td>${batch.uploaded_by || 'System'}</td>
                        <td>
                            <div class="batch-actions">
                                <button class="batch-action-btn view" onclick="viewBatchDetails('${batch.id}')" title="View Details">
                                    👁️
                                </button>
                                <button class="batch-action-btn download" onclick="downloadBatchReport('${batch.id}')" title="Download Report">
                                    💾
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');
            
            tbody.innerHTML = batchRows;
            
            // Update select all checkbox state
            updateBatchSelectAllState();
        }

        // Update batch pagination controls
        function updateBatchPagination(pagination) {
            const paginationInfo = document.getElementById('batchPaginationInfo');
            const currentPageInfo = document.getElementById('batchCurrentPageInfo');
            const prevBtn = document.getElementById('batchPrevBtn');
            const nextBtn = document.getElementById('batchNextBtn');
            
            const startRecord = ((pagination.current_page - 1) * pagination.page_size) + 1;
            const endRecord = Math.min(pagination.current_page * pagination.page_size, pagination.total_count);
            
            paginationInfo.textContent = `Showing ${startRecord} - ${endRecord} of ${pagination.total_count} uploads`;
            currentPageInfo.textContent = `Page ${pagination.current_page} of ${pagination.total_pages}`;
            
            prevBtn.disabled = !pagination.has_prev;
            nextBtn.disabled = !pagination.has_next;
        }

        // Update select all checkbox state
        function updateBatchSelectAllState() {
            const selectAllPage = document.getElementById('batchSelectAllPage');
            const rowCheckboxes = document.querySelectorAll('.batch-row-checkbox');
            
            if (rowCheckboxes.length === 0) {
                selectAllPage.checked = false;
                selectAllPage.indeterminate = false;
                return;
            }
            
            const checkedCount = Array.from(rowCheckboxes).filter(cb => cb.checked).length;
            
            if (checkedCount === 0) {
                selectAllPage.checked = false;
                selectAllPage.indeterminate = false;
            } else if (checkedCount === rowCheckboxes.length) {
                selectAllPage.checked = true;
                selectAllPage.indeterminate = false;
            } else {
                selectAllPage.checked = false;
                selectAllPage.indeterminate = true;
            }
        }

        // Select all filtered uploads
        async function selectAllFilteredUploads() {
            try {
                // Build query parameters for current filter
                const params = new URLSearchParams();
                if (batchDateFilter) {
                    params.append('date_filter', batchDateFilter);
                }
                
                const response = await fetch(`/api/uploaded-files/ids?${params}`);
                if (!response.ok) {
                    throw new Error(`Failed to fetch upload IDs: ${response.status}`);
                }
                
                const data = await response.json();
                if (!data.success) {
                    throw new Error(data.error || 'Failed to fetch upload IDs');
                }
                
                // Add all IDs to selection
                data.upload_ids.forEach(id => selectedBatchIds.add(id));
                
                // Update UI
                updateBatchSelectAllState();
                logActivity(`✅ Selected all ${data.upload_ids.length} filtered uploads`);
                
            } catch (error) {
                console.error('Error selecting all uploads:', error);
                logActivity(`❌ Failed to select all uploads: ${error.message}`, 'error');
            }
        }

        // View batch details in modal
        async function viewBatchDetails(batchId) {
            try {
                const response = await fetch(`/api/uploaded-files/${batchId}/details`);
                if (!response.ok) {
                    throw new Error(`Failed to fetch batch details: ${response.status}`);
                }
                
                const data = await response.json();
                if (!data.success) {
                    throw new Error(data.error || 'Failed to load batch details');
                }
                
                // Create and show modal with batch details
                showBatchDetailsModal(data.upload_details, data.upload_details.rows);
                
            } catch (error) {
                console.error('Error viewing batch details:', error);
                showToast(`Failed to load batch details: ${error.message}`, 'error');
            }
        }

        // Show batch details modal
        function showBatchDetailsModal(upload, rows) {
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content">
                    <span class="modal-close" onclick="closeModal(this)">&times;</span>
                    <h3>📄 Batch Upload Details</h3>
                    <div class="batch-detail-info">
                        <div><strong>File:</strong> ${upload.original_filename || upload.filename}</div>
                        <div><strong>Uploaded:</strong> ${new Date(upload.uploaded_at).toLocaleString('en-IN')}</div>
                        <div><strong>Status:</strong> <span class="batch-status ${upload.status.toLowerCase()}">${upload.status}</span></div>
                        <div><strong>Total Records:</strong> ${upload.total_records}</div>
                        <div><strong>Success:</strong> ${upload.success_records}</div>
                        <div><strong>Failed:</strong> ${upload.failed_records}</div>
                        ${upload.processing_errors ? `<div><strong>Errors:</strong> <pre>${JSON.stringify(upload.processing_errors, null, 2)}</pre></div>` : ''}
                    </div>
                    ${rows && rows.length > 0 ? `
                        <h4>Sample Records (First 10)</h4>
                        <div class="table-container">
                            <table class="csv-table">
                                <thead>
                                    <tr>
                                        <th>Row #</th>
                                        <th>Customer Name</th>
                                        <th>Phone</th>
                                        <th>Loan ID</th>
                                        <th>Status</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${rows.slice(0, 10).map((row, index) => `
                                        <tr>
                                            <td>${index + 1}</td>
                                            <td>${row.customer_name || 'N/A'}</td>
                                            <td>${row.phone || 'N/A'}</td>
                                            <td>${row.loan_id || 'N/A'}</td>
                                            <td><span class="batch-status ${(row.processing_status || 'unknown').toLowerCase()}">${row.processing_status || 'Unknown'}</span></td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    ` : ''}
                </div>
            `;
            
            document.body.appendChild(modal);
            modal.style.display = 'flex';
        }

        // Download batch report
        function downloadBatchReport(batchId) {
            // Create downloadable CSV report
            const link = document.createElement('a');
            link.href = `/api/uploaded-files/${batchId}/download`;
            link.download = `batch_report_${batchId}.csv`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            
            showToast('Batch report download started', 'info');
        }

        // Close modal
        function closeModal(element) {
            const modal = element.closest('.modal');
            if (modal) {
                modal.remove();
            }
        }

        // Utility function to truncate text
        function truncateText(text, maxLength) {
            if (text.length <= maxLength) return text;
            return text.substring(0, maxLength - 3) + '...';
        }

        // === CALL STATUS TRACKING FUNCTIONS ===
        
        let autoRefreshInterval = null;
        let isAutoRefresh = false;

        // Load call statuses from the API
        async function loadCallStatuses() {
            try {
                logActivity('📞 Loading call status data...');
                
                const response = await fetch('/api/call-statuses');
                if (!response.ok) {
                    throw new Error(`Failed to fetch call statuses: ${response.status}`);
                }
                
                const data = await response.json();
                if (!data.success) {
                    throw new Error(data.error || 'Failed to load call statuses');
                }
                
                updateCallStatusStats(data.statuses);
                populateCallStatusTable(data.statuses);
                
                logActivity(`✅ Loaded ${data.statuses.length} call status updates`);
                
            } catch (error) {
                console.error('Error loading call statuses:', error);
                logActivity(`❌ Failed to load call statuses: ${error.message}`);
                showToast(`Failed to load call statuses: ${error.message}`, 'error');
            }
        }

        // Update call status statistics
        function updateCallStatusStats(statuses) {
            // Group statuses by latest status per call
            const callStatusMap = new Map();
            
            statuses.forEach(status => {
                const existing = callStatusMap.get(status.call_sid);
                if (!existing || new Date(status.timestamp) > new Date(existing.timestamp)) {
                    callStatusMap.set(status.call_sid, status);
                }
            });
            
            const latestStatuses = Array.from(callStatusMap.values());
            
            // Calculate statistics
            const totalCalls = latestStatuses.length;
            const inProgressCalls = latestStatuses.filter(s => 
                s.status === 'call_in_progress' || s.status === 'ringing' || s.status === 'initiated'
            ).length;
            const completedCalls = latestStatuses.filter(s => s.status === 'call_completed').length;
            const failedCalls = latestStatuses.filter(s => s.status === 'call_failed').length;
            
            // Update DOM elements
            document.getElementById('totalCallsStat').textContent = totalCalls;
            document.getElementById('inProgressCallsStat').textContent = inProgressCalls;
            document.getElementById('completedCallsStat').textContent = completedCalls;
            document.getElementById('failedCallsStat').textContent = failedCalls;
        }

        // Populate call status table
        function populateCallStatusTable(statuses) {
            const tbody = document.getElementById('callStatusTableBody');
            
            if (statuses.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="7" style="text-align: center; padding: 20px; color: #666;">
                            📞 No call status updates found
                        </td>
                    </tr>
                `;
                return;
            }
            
            // Sort by timestamp descending (newest first)
            const sortedStatuses = statuses.sort((a, b) => 
                new Date(b.timestamp) - new Date(a.timestamp)
            );
            
            const statusRows = sortedStatuses.slice(0, 50).map(status => {
                const timestamp = new Date(status.timestamp);
                const formattedTime = timestamp.toLocaleString('en-IN', {
                    day: '2-digit',
                    month: 'short',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit'
                });
                
                const statusClass = status.status.toLowerCase().replace(/_/g, '_');
                
                return `
                    <tr>
                        <td title="${status.customer_name}">
                            ${truncateText(status.customer_name, 20)}
                        </td>
                        <td>${status.customer_phone}</td>
                        <td title="${status.call_sid}">
                            ${truncateText(status.call_sid, 15)}
                        </td>
                        <td>
                            <span class="call-status-badge status-${statusClass}">
                                ${status.status.replace(/_/g, ' ')}
                            </span>
                        </td>
                        <td title="${status.message || 'No message'}">
                            ${truncateText(status.message || 'No message', 30)}
                        </td>
                        <td>${formattedTime}</td>
                        <td>
                            <div class="call-actions">
                                <button class="call-action-btn view" onclick="viewCallDetails('${status.call_sid}')" title="View All Updates">
                                    👁️
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');
            
            tbody.innerHTML = statusRows;
        }

        // View call details
        async function viewCallDetails(callSid) {
            try {
                const response = await fetch(`/api/call-statuses/${callSid}`);
                if (!response.ok) {
                    throw new Error(`Failed to fetch call details: ${response.status}`);
                }
                
                const data = await response.json();
                if (!data.success) {
                    throw new Error(data.error || 'Failed to load call details');
                }
                
                showCallDetailsModal(data);
                
            } catch (error) {
                console.error('Error viewing call details:', error);
                showToast(`Failed to load call details: ${error.message}`, 'error');
            }
        }

        // Show call details modal
        function showCallDetailsModal(callData) {
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.innerHTML = `
                <div class="modal-content">
                    <div class="modal-header">
                        <h3>📞 Call Details - ${callData.call_sid}</h3>
                        <button class="modal-close" onclick="closeModal(this)">✖️</button>
                    </div>
                    <div class="modal-body">
                        <div class="call-info">
                            <p><strong>Customer:</strong> ${callData.customer_name || 'Unknown'}</p>
                            <p><strong>Phone:</strong> ${callData.customer_phone || 'Unknown'}</p>
                            <p><strong>Call SID:</strong> ${callData.call_sid}</p>
                        </div>
                        <h4>Status Updates:</h4>
                        <div class="status-timeline">
                            ${callData.statuses.map(status => {
                                const timestamp = new Date(status.timestamp);
                                const formattedTime = timestamp.toLocaleString('en-IN');
                                const statusClass = status.status.toLowerCase().replace(/_/g, '_');
                                
                                return `
                                    <div class="status-timeline-item">
                                        <div class="status-timestamp">${formattedTime}</div>
                                        <div class="status-info">
                                            <span class="call-status-badge status-${statusClass}">
                                                ${status.status.replace(/_/g, ' ')}
                                            </span>
                                            <div class="status-message">${status.message || 'No message'}</div>
                                        </div>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    </div>
                </div>
            `;
            
            document.body.appendChild(modal);
            modal.style.display = 'flex';
        }

        // Toggle auto refresh
        function toggleAutoRefresh() {
            const button = document.querySelector('.auto-refresh-button');
            const text = document.getElementById('autoRefreshText');
            
            if (isAutoRefresh) {
                // Stop auto refresh
                clearInterval(autoRefreshInterval);
                isAutoRefresh = false;
                button.classList.remove('active');
                text.textContent = '▶️ Auto Refresh';
                logActivity('⏸️ Auto refresh stopped');
            } else {
                // Start auto refresh
                autoRefreshInterval = setInterval(loadCallStatuses, 10000); // Every 10 seconds
                isAutoRefresh = true;
                button.classList.add('active');
                text.textContent = '⏸️ Stop Auto';
                logActivity('▶️ Auto refresh started (10s interval)');
            }
        }

        // Populate filter dropdown options
        function populateFilterOptions() {
            const states = [...new Set(customers.map(c => c.state).filter(Boolean))].sort();
            const clusters = [...new Set(customers.flatMap(c => c.loans.map(l => l.cluster).filter(Boolean)))].sort();
            const branches = [...new Set(customers.flatMap(c => c.loans.map(l => l.branch).filter(Boolean)))].sort();
            const employees = [...new Set(customers.flatMap(c => c.loans.map(l => l.employee_name).filter(Boolean)))].sort();

            populateSelect('stateFilter', states);
            populateSelect('clusterFilter', clusters);
            populateSelect('branchFilter', branches);
            populateSelect('employeeFilter', employees);
        }

        function populateSelect(selectId, options) {
            const select = document.getElementById(selectId);
            const currentValue = select.value;
            
            // Keep the "All" option and add new options
            select.innerHTML = select.children[0].outerHTML;
            options.forEach(option => {
                const optionElement = document.createElement('option');
                optionElement.value = option;
                optionElement.textContent = option;
                select.appendChild(optionElement);
            });
            
            // Restore selection if it still exists
            if (options.includes(currentValue)) {
                select.value = currentValue;
            }
        }

        // Apply filters
        function applyFilters() {
            const searchTerm = document.getElementById('searchInput').value.toLowerCase();
            const uploadDateFilter = document.getElementById('uploadDateFilter').value;
            const callStatusFilter = document.getElementById('callStatusFilter').value;
            const stateFilter = document.getElementById('stateFilter').value;
            const clusterFilter = document.getElementById('clusterFilter').value;
            const branchFilter = document.getElementById('branchFilter').value;
            const employeeFilter = document.getElementById('employeeFilter').value;
            const startDate = document.getElementById('startDate').value;
            const endDate = document.getElementById('endDate').value;

            filteredCustomers = customers.filter(customer => {
                // Search filter
                if (searchTerm) {
                    const searchMatch = 
                        customer.full_name.toLowerCase().includes(searchTerm) ||
                        customer.primary_phone.includes(searchTerm) ||
                        customer.loans.some(loan => loan.loan_id.toLowerCase().includes(searchTerm));
                    if (!searchMatch) return false;
                }

                // Upload date filter
                if (uploadDateFilter && uploadDateFilter !== 'custom') {
                    if (!matchesDateFilter(customer.first_uploaded_at, uploadDateFilter)) return false;
                }

                // Custom date range filter
                if (uploadDateFilter === 'custom' && (startDate || endDate)) {
                    const uploadDate = new Date(customer.first_uploaded_at).toISOString().split('T')[0];
                    if (startDate && uploadDate < startDate) return false;
                    if (endDate && uploadDate > endDate) return false;
                }

                // Call status filter
                if (callStatusFilter) {
                    // Map status values
                    const customerStatus = mapCallStatus(customer.call_status || 'ready');
                    if (customerStatus !== callStatusFilter) return false;
                }

                // State filter
                if (stateFilter && customer.state !== stateFilter) return false;

                // Cluster/Branch/Employee filters (check loans)
                if (clusterFilter || branchFilter || employeeFilter) {
                    const hasMatchingLoan = customer.loans.some(loan => {
                        if (clusterFilter && loan.cluster !== clusterFilter) return false;
                        if (branchFilter && loan.branch !== branchFilter) return false;
                        if (employeeFilter && loan.employee_name !== employeeFilter) return false;
                        return true;
                    });
                    if (!hasMatchingLoan) return false;
                }

                return true;
            });

            currentPage = 1;
            renderCustomerTable();
            updatePaginationInfo();
            updateStatistics();
        }

        // Date filter matching with IST timezone support
        function matchesDateFilter(dateString, filter) {
            const date = new Date(dateString);
            const today = new Date();
            const yesterday = new Date(today);
            yesterday.setDate(yesterday.getDate() - 1);

            // Convert to IST for accurate date comparison
            const istDate = new Date(date.toLocaleString('en-US', {timeZone: 'Asia/Kolkata'}));
            const istToday = new Date(today.toLocaleString('en-US', {timeZone: 'Asia/Kolkata'}));
            const istYesterday = new Date(yesterday.toLocaleString('en-US', {timeZone: 'Asia/Kolkata'}));

            switch (filter) {
                case 'today':
                    return istDate.toDateString() === istToday.toDateString();
                case 'yesterday':
                    return istDate.toDateString() === istYesterday.toDateString();
                case 'this-week':
                    const weekStart = new Date(istToday);
                    weekStart.setDate(istToday.getDate() - istToday.getDay());
                    return istDate >= weekStart;
                case 'last-week':
                    const lastWeekStart = new Date(istToday);
                    lastWeekStart.setDate(istToday.getDate() - istToday.getDay() - 7);
                    const lastWeekEnd = new Date(lastWeekStart);
                    lastWeekEnd.setDate(lastWeekStart.getDate() + 6);
                    return istDate >= lastWeekStart && istDate <= lastWeekEnd;
                case 'this-month':
                    return istDate.getMonth() === istToday.getMonth() && istDate.getFullYear() === istToday.getFullYear();
                default:
                    return true;
            }
        }

        // Map call status for display
        function mapCallStatus(status) {
            const statusMap = {
                'ready': 'ready',
                'not_initiated': 'ready',
                'calling': 'calling',
                'initiated': 'calling',
                'ringing': 'calling',
                'call_in_progress': 'in-progress',
                'in_progress': 'in-progress',
                'call_completed': 'completed',
                'completed': 'completed',
                'call_failed': 'failed',
                'failed': 'failed',
                'agent_transfer': 'agent-transfer',
                'disconnected': 'failed'
            };
            return statusMap[status] || 'ready';
        }

        // Render customer table
        function renderCustomerTable() {
            console.log('=== RENDER CUSTOMER TABLE START ===');
            console.log('recordsPerPage:', recordsPerPage, '(type:', typeof recordsPerPage, ')');
            console.log('currentPage:', currentPage);
            console.log('filteredCustomers.length:', filteredCustomers.length);
            
            const tbody = document.getElementById('customerTableBody');
            
            let pageCustomers;
            if (recordsPerPage === 'all') {
                pageCustomers = filteredCustomers;
                console.log('Mode: Showing ALL customers, count:', pageCustomers.length);
            } else {
                const startIndex = (currentPage - 1) * recordsPerPage;
                const endIndex = startIndex + recordsPerPage;
                pageCustomers = filteredCustomers.slice(startIndex, endIndex);
                console.log(`Mode: Pagination - startIndex: ${startIndex}, endIndex: ${endIndex}`);
                console.log(`Showing customers ${startIndex + 1} to ${Math.min(endIndex, filteredCustomers.length)} of ${filteredCustomers.length}`);
                console.log('pageCustomers.length:', pageCustomers.length);
            }
            
            // Update displayedCustomers for select all functionality
            displayedCustomers = pageCustomers;

            if (pageCustomers.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="20" style="text-align: center; padding: 40px; color: #666;">
                            ${filteredCustomers.length === 0 ? 'No customers found' : 'No customers match the current filters'}
                        </td>
                    </tr>
                `;
                return;
            }

            tbody.innerHTML = pageCustomers.map((customer, index) => {
                // Calculate serial number based on pagination
                let serialNo;
                if (recordsPerPage === 'all') {
                    serialNo = index + 1;
                } else {
                    serialNo = (currentPage - 1) * recordsPerPage + index + 1;
                }
                
                const loan = customer.loans[0] || {};
                const uploadDate = getUploadDateBadge(customer.first_uploaded_at);
                const callStatus = mapCallStatus(customer.call_status || 'ready');
                
                return `
                    <tr class="customer-row ${callStatus}" data-customer-id="${customer.id}">
                        <td>
                            <input type="checkbox" value="${customer.id}" 
                                   ${selectedCustomers.has(customer.id) ? 'checked' : ''}
                                   onchange="toggleCustomerSelection('${customer.id}')">
                        </td>
                        <td style="text-align: center; font-weight: 600; color: #495057;">
                            ${serialNo}
                        </td>
                        <td>
                            <span class="upload-date-badge ${uploadDate.class}">${uploadDate.text}</span>
                            <div style="font-size: 0.8em; color: #666; margin-top: 2px;">
                                ${formatDate(customer.first_uploaded_at)}
                            </div>
                        </td>
                        <td><strong>${customer.full_name}</strong></td>
                        <td>${customer.primary_phone}</td>
                        <td><code>${loan.loan_id || 'N/A'}</code></td>
                        <td>₹${formatCurrency(loan.outstanding_amount || 0)}</td>
                        <td>${formatDate(loan.next_due_date) || 'N/A'}</td>
                        <td><span class="badge">${customer.state || 'N/A'}</span></td>
                        <td>${loan.cluster || 'N/A'}</td>
                        <td>${loan.branch || 'N/A'}</td>
                        <td>${loan.branch_contact_number || 'N/A'}</td>
                        <td>${loan.employee_name || 'N/A'}</td>
                        <td>${loan.employee_id || 'N/A'}</td>
                        <td>${loan.employee_contact_number || 'N/A'}</td>
                        <td>${formatDate(loan.last_paid_date) || 'N/A'}</td>
                        <td>₹${formatCurrency(loan.last_paid_amount || 0)}</td>
                        <td>₹${formatCurrency(loan.due_amount || 0)}</td>
                        <td>
                            <span class="status-badge status-${callStatus}">
                                ${callStatus.replace('-', ' ')}
                            </span>
                        </td>
                        <td>
                            <button class="action-btn btn-call" onclick="callCustomer('${customer.id}')">
                                📞 Call
                            </button>
                            <button class="action-btn btn-details" onclick="showCustomerDetails('${customer.id}')">
                                👁️ Details
                            </button>
                        </td>
                    </tr>
                `;
            }).join('');

            console.log('Table HTML generated, rows count:', pageCustomers.length);
            updatePaginationInfo();
            console.log('=== RENDER CUSTOMER TABLE END ===');
        }

        // Get upload date badge with IST timezone support
        function getUploadDateBadge(dateString) {
            if (!dateString) return { class: 'date-older', text: 'Unknown' };
            
            const date = new Date(dateString);
            
            // Get current date in IST
            const now = new Date();
            const istNow = new Date(now.toLocaleString('en-US', {timeZone: 'Asia/Kolkata'}));
            
            // Convert upload date to IST
            const istDate = new Date(date.toLocaleString('en-US', {timeZone: 'Asia/Kolkata'}));
            
            // Get only the date part (ignore time)
            const todayDateString = istNow.toDateString();
            const uploadDateString = istDate.toDateString();
            
            // Compare dates
            if (uploadDateString === todayDateString) {
                return { class: 'date-today', text: 'Today' };
            }
            
            // Check for yesterday
            const yesterday = new Date(istNow);
            yesterday.setDate(yesterday.getDate() - 1);
            const yesterdayDateString = yesterday.toDateString();
            
            if (uploadDateString === yesterdayDateString) {
                return { class: 'date-yesterday', text: 'Yesterday' };
            }
            
            // Calculate days difference more accurately
            const timeDiff = istNow.setHours(0,0,0,0) - istDate.setHours(0,0,0,0);
            const daysDiff = Math.floor(timeDiff / (1000 * 60 * 60 * 24));
            
            if (daysDiff <= 7 && daysDiff > 0) {
                return { class: 'date-week', text: `${daysDiff}d ago` };
            } else if (daysDiff < 0) {
                // Future date
                return { class: 'date-future', text: 'Future' };
            }
            
            return { class: 'date-older', text: `${daysDiff}d ago` };
        }

        // Format currency
        function formatCurrency(amount) {
            return new Intl.NumberFormat('en-IN').format(amount);
        }

        // Format date with IST timezone
        function formatDate(dateString) {
            if (!dateString) return null;
            const date = new Date(dateString);
            return date.toLocaleDateString('en-IN', {
                timeZone: 'Asia/Kolkata',
                day: '2-digit',
                month: '2-digit',
                year: 'numeric'
            });
        }

        // Format date and time with IST timezone
        function formatDateTime(dateString) {
            if (!dateString) return null;
            const date = new Date(dateString);
            return date.toLocaleString('en-IN', {
                timeZone: 'Asia/Kolkata',
                day: '2-digit',
                month: '2-digit', 
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: true
            });
        }

        // Get IST current time
        function getCurrentISTTime() {
            return new Date().toLocaleString('en-IN', {
                timeZone: 'Asia/Kolkata',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: true
            });
        }

        // Select all filtered customers
        function selectAllFilteredCustomers() {
            if (displayedCustomers.length === 0) {
                showNotification('No customers available to select', 'warning');
                return;
            }
            
            // Select all displayed customers
            displayedCustomers.forEach(customer => {
                selectedCustomers.add(customer.id);
            });
            
            updateSelectionCount();
            renderCustomerTable(); // Re-render to update checkboxes
            showNotification(`Selected all ${displayedCustomers.length} filtered customers`, 'success');
        }

        // Toggle customer selection
        function toggleCustomerSelection(customerId) {
            if (selectedCustomers.has(customerId)) {
                selectedCustomers.delete(customerId);
            } else {
                selectedCustomers.add(customerId);
            }
            updateSelectionCount();
        }

        // Update selection count
        function updateSelectionCount() {
            const count = selectedCustomers.size;
            document.getElementById('selectedCount').textContent = `${count} selected`;
            document.getElementById('selectedCountText').textContent = count;
            
            const hasSelection = count > 0;
            document.getElementById('callSelectedBtn').disabled = !hasSelection;
            document.getElementById('updateSelectedStatusBtn').disabled = !hasSelection;
            document.getElementById('exportSelectedBtn').disabled = !hasSelection;
        }

        // Update pagination info
        function updatePaginationInfo() {
            console.log('=== UPDATE PAGINATION INFO ===');
            console.log('recordsPerPage:', recordsPerPage, '(type:', typeof recordsPerPage, ')');
            console.log('currentPage:', currentPage);
            console.log('filteredCustomers.length:', filteredCustomers.length);
            
            const totalRecords = filteredCustomers.length;
            
            if (recordsPerPage === 'all') {
                document.getElementById('paginationInfo').innerHTML = 
                    `<strong>Showing all ${totalRecords} records</strong><br>
                     <small style="color: #6c757d;">Serial No. 1 to ${totalRecords}</small>`;
                
                // Update page jump controls
                document.getElementById('pageJumpInput').value = 1;
                document.getElementById('pageJumpInput').max = 1;
                document.getElementById('totalPagesSpan').textContent = '1';
                
                // Update dynamic status
                document.getElementById('currentViewInfo').textContent = 
                    `📊 Currently viewing all ${totalRecords} records`;
                document.getElementById('serialRangeInfo').textContent = 
                    `🔢 Serial No. 1 to ${totalRecords}`;
                
                document.getElementById('prevPageBtn').disabled = true;
                document.getElementById('nextPageBtn').disabled = true;
                document.getElementById('pageJumpInput').disabled = true;
            } else {
                const startRecord = (currentPage - 1) * recordsPerPage + 1;
                const endRecord = Math.min(currentPage * recordsPerPage, totalRecords);
                const totalPages = Math.ceil(totalRecords / recordsPerPage);
                
                console.log('Calculated values:');
                console.log('  startRecord:', startRecord);
                console.log('  endRecord:', endRecord);
                console.log('  totalPages:', totalPages);

                document.getElementById('paginationInfo').innerHTML = 
                    `<strong>Showing ${startRecord}-${endRecord} of ${totalRecords} records</strong><br>
                     <small style="color: #6c757d;">Serial No. ${startRecord} to ${endRecord}</small>`;
                
                // Update page jump controls
                document.getElementById('pageJumpInput').value = currentPage;
                document.getElementById('pageJumpInput').max = totalPages;
                document.getElementById('totalPagesSpan').textContent = totalPages;
                
                // Update dynamic status
                document.getElementById('currentViewInfo').textContent = 
                    `📊 Currently viewing records ${startRecord}-${endRecord} of ${totalRecords} total`;
                document.getElementById('serialRangeInfo').textContent = 
                    `🔢 Serial No. ${startRecord} to ${endRecord}`;
                
                document.getElementById('prevPageBtn').disabled = currentPage === 1;
                document.getElementById('nextPageBtn').disabled = currentPage === totalPages || totalPages === 0;
                document.getElementById('pageJumpInput').disabled = totalPages <= 1;
            }
            console.log('=== END UPDATE PAGINATION INFO ===');
        }

        // Jump to specific page
        function jumpToPage(pageNumber) {
            const totalPages = Math.ceil(filteredCustomers.length / recordsPerPage);
            const page = parseInt(pageNumber);
            
            if (page >= 1 && page <= totalPages) {
                currentPage = page;
                renderCustomerTable();
                updatePaginationInfo();
                showNotification(`Jumped to page ${page}`, 'info');
            } else {
                document.getElementById('pageJumpInput').value = currentPage;
                showNotification(`Please enter a page number between 1 and ${totalPages}`, 'warning');
            }
        }

        // Update statistics with IST timezone
        function updateStatistics() {
            const totalCustomers = customers.length;
            
            // Calculate today's uploads using IST timezone
            const istToday = new Date().toLocaleDateString('en-IN', {timeZone: 'Asia/Kolkata'});
            const todayUploads = customers.filter(c => {
                const uploadDate = new Date(c.first_uploaded_at).toLocaleDateString('en-IN', {timeZone: 'Asia/Kolkata'});
                return uploadDate === istToday;
            }).length;
            
            const statusCounts = customers.reduce((acc, customer) => {
                const status = mapCallStatus(customer.call_status || 'ready');
                acc[status] = (acc[status] || 0) + 1;
                return acc;
            }, {});

            document.getElementById('totalCustomersStat').textContent = totalCustomers;
            document.getElementById('todayUploadsStat').textContent = todayUploads;
            document.getElementById('readyToCallStat').textContent = statusCounts.ready || 0;
            document.getElementById('activeCallsStat').textContent = statusCounts['in-progress'] || 0;
            document.getElementById('completedCallsStat').textContent = statusCounts.completed || 0;
            document.getElementById('totalCustomersDisplay').textContent = `Total: ${totalCustomers}`;
        }

        // Handle file upload
        async function handleFileUpload() {
            const fileInput = document.getElementById('fileInput');
            const file = fileInput.files[0];
            
            if (!file) return;
            
            if (!file.name.toLowerCase().endsWith('.csv')) {
                alert('Please select a CSV file');
                return;
            }

            const formData = new FormData();
            formData.append('file', file);

            try {
                showUploadProgress(true);
                logActivity(`Uploading file: ${file.name}`);

                const response = await fetch('/api/upload-customers', {
                    method: 'POST',
                    body: formData
                });

                const result = await response.json();
                
                if (result.success) {
                    const successMessage = `Upload successful: ${result.processing_results.success_records} records processed`;
                    logActivity(`✅ ${successMessage}`);
                    showToast(successMessage, 'success');
                    
                    // Refresh customer data from database after successful upload
                    setTimeout(() => {
                        logActivity('🔄 Refreshing customer data after upload...');
                        loadCustomerData(true);
                    }, 1500);
                } else {
                    throw new Error(result.message || 'Upload failed');
                }
            } catch (error) {
                console.error('Upload error:', error);
                logActivity(`Upload failed: ${error.message}`, 'error');
                alert(`Upload failed: ${error.message}`);
            } finally {
                showUploadProgress(false);
                fileInput.value = '';
            }
        }

        // Call customer with enhanced error handling and status updates
        async function callCustomer(customerId) {
            try {
                const customer = customers.find(c => c.id === customerId);
                if (!customer) {
                    alert('Customer not found');
                    return;
                }

                logActivity(`Initiating call for ${customer.full_name} (${customer.primary_phone})`);
                
                // Disable the call button for this customer to prevent double calls
                const callBtn = document.querySelector(`button[onclick="callCustomer('${customerId}')"]`);
                if (callBtn) {
                    callBtn.disabled = true;
                    callBtn.textContent = '📞 Calling...';
                }

                const response = await fetch('/api/trigger-single-call', {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    },
                    body: JSON.stringify({ customer_id: customerId })
                });

                const result = await response.json();
                
                if (response.ok && result.success) {
                    logActivity(`✅ Call initiated successfully for ${customer.full_name}`);
                    // Update customer status in the UI
                    updateCustomerCallStatus(customerId, 'calling', 'Call initiated');
                    
                    // Show success toast notification
                    showToast(`Call started for ${customer.full_name}`, 'success');
                } else {
                    throw new Error(result.message || `HTTP ${response.status}: ${response.statusText}`);
                }
            } catch (error) {
                console.error('Call error:', error);
                logActivity(`❌ Call failed: ${error.message}`, 'error');
                alert(`Call failed: ${error.message}`);
                
                // Re-enable the call button on error
                const callBtn = document.querySelector(`button[onclick="callCustomer('${customerId}')"]`);
                if (callBtn) {
                    callBtn.disabled = false;
                    callBtn.textContent = '📞 Call';
                }
            }
        }

        // Call selected customers with enhanced progress tracking
        async function callSelectedCustomers() {
            if (selectedCustomers.size === 0) {
                alert('Please select customers to call');
                return;
            }
            
            const customerCount = selectedCustomers.size;
            const selectedCustomerNames = Array.from(selectedCustomers).map(id => {
                const customer = customers.find(c => c.id === id);
                return customer ? customer.full_name : `ID: ${id}`;
            }).slice(0, 3).join(', ');
            
            const confirmMessage = customerCount <= 3 
                ? `Call ${customerCount} selected customers: ${selectedCustomerNames}?`
                : `Call ${customerCount} selected customers: ${selectedCustomerNames} and ${customerCount - 3} more?`;
            
            if (!confirm(confirmMessage)) return;
            
            try {
                logActivity(`🚀 Initiating bulk calls for ${customerCount} customers`);
                
                // Disable bulk call button during processing
                const bulkBtn = document.getElementById('callSelectedBtn');
                const originalText = bulkBtn.textContent;
                bulkBtn.disabled = true;
                bulkBtn.textContent = `📞 Calling ${customerCount} customers...`;

                const response = await fetch('/api/trigger-bulk-calls', {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/json',
                        'Accept': 'application/json'
                    },
                    body: JSON.stringify({ customer_ids: Array.from(selectedCustomers) })
                });

                const result = await response.json();
                
                if (response.ok && result.success) {
                    logActivity(`✅ Bulk calls initiated successfully for ${customerCount} customers`);
                    
                    // Update status for all selected customers
                    selectedCustomers.forEach(customerId => {
                        updateCustomerCallStatus(customerId, 'calling', 'Bulk call initiated');
                    });
                    
                    // Show success notification
                    showToast(`Bulk calls started for ${customerCount} customers`, 'success');
                    
                    // Clear selection
                    selectedCustomers.clear();
                    updateSelectionCount();
                    document.getElementById('selectAll').checked = false;
                } else {
                    throw new Error(result.message || `HTTP ${response.status}: ${response.statusText}`);
                }
            } catch (error) {
                console.error('Bulk call error:', error);
                logActivity(`❌ Bulk calls failed: ${error.message}`, 'error');
                alert(`Bulk calls failed: ${error.message}`);
            } finally {
                // Re-enable bulk call button
                const bulkBtn = document.getElementById('callSelectedBtn');
                bulkBtn.disabled = selectedCustomers.size === 0;
                bulkBtn.textContent = originalText;
            }
        }

        // Show customer details
        function showCustomerDetails(customerId) {
            const customer = customers.find(c => c.id === customerId);
            if (!customer) return;

            const modalContent = document.getElementById('customerDetailsContent');
            modalContent.innerHTML = `
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px;">
                    <div>
                        <h4>👤 Customer Information</h4>
                        <p><strong>Name:</strong> ${customer.full_name}</p>
                        <p><strong>Phone:</strong> ${customer.primary_phone}</p>
                        <p><strong>State:</strong> ${customer.state || 'N/A'}</p>
                        <p><strong>Email:</strong> ${customer.email || 'N/A'}</p>
                        <p><strong>First Uploaded:</strong> ${formatDate(customer.first_uploaded_at)}</p>
                        <p><strong>Last Contact:</strong> ${formatDate(customer.last_contact_date) || 'Never'}</p>
                    </div>
                    <div>
                        <h4>💰 Loan Information</h4>
                        ${customer.loans.map(loan => `
                            <div style="border: 1px solid #ddd; padding: 10px; margin: 10px 0; border-radius: 6px;">
                                <p><strong>Loan ID:</strong> ${loan.loan_id}</p>
                                <p><strong>Outstanding:</strong> ₹${formatCurrency(loan.outstanding_amount)}</p>
                                <p><strong>Due Amount:</strong> ₹${formatCurrency(loan.due_amount)}</p>
                                <p><strong>Next Due:</strong> ${formatDate(loan.next_due_date) || 'N/A'}</p>
                                <p><strong>Last Paid:</strong> ₹${formatCurrency(loan.last_paid_amount)} on ${formatDate(loan.last_paid_date) || 'N/A'}</p>
                                <p><strong>Cluster:</strong> ${loan.cluster || 'N/A'}</p>
                                <p><strong>Branch:</strong> ${loan.branch || 'N/A'}</p>
                                <p><strong>Employee:</strong> ${loan.employee_name || 'N/A'} (${loan.employee_id || 'N/A'})</p>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
            
            document.getElementById('customerModal').style.display = 'flex';
        }

        // Clear all filters
        function clearAllFilters() {
            document.getElementById('searchInput').value = '';
            document.getElementById('uploadDateFilter').value = '';
            document.getElementById('callStatusFilter').value = '';
            document.getElementById('stateFilter').value = '';
            document.getElementById('clusterFilter').value = '';
            document.getElementById('branchFilter').value = '';
            document.getElementById('employeeFilter').value = '';
            document.getElementById('startDate').value = '';
            document.getElementById('endDate').value = '';
            document.getElementById('customDateRange').style.display = 'none';
            
            applyFilters();
        }

        // Export selected customers
        function exportSelectedCustomers() {
            if (selectedCustomers.size === 0) return;
            
            const selectedData = customers.filter(c => selectedCustomers.has(c.id));
            const csvContent = convertToCSV(selectedData);
            downloadCSV(csvContent, `exported_customers_${new Date().toISOString().split('T')[0]}.csv`);
        }

        // Convert to CSV
        function convertToCSV(data) {
            const headers = [
                'Name', 'Phone', 'State', 'Loan ID', 'Outstanding Amount', 'Due Amount',
                'Next Due Date', 'Last Paid Date', 'Last Paid Amount', 'Cluster',
                'Branch', 'Branch Contact', 'Employee', 'Employee ID', 'Employee Contact',
                'Upload Date', 'Call Status'
            ];
            
            const rows = data.map(customer => {
                const loan = customer.loans[0] || {};
                return [
                    customer.full_name,
                    customer.primary_phone,
                    customer.state || '',
                    loan.loan_id || '',
                    loan.outstanding_amount || 0,
                    loan.due_amount || 0,
                    loan.next_due_date || '',
                    loan.last_paid_date || '',
                    loan.last_paid_amount || 0,
                    loan.cluster || '',
                    loan.branch || '',
                    loan.branch_contact_number || '',
                    loan.employee_name || '',
                    loan.employee_id || '',
                    loan.employee_contact_number || '',
                    customer.first_uploaded_at,
                    customer.call_status || 'ready'
                ];
            });
            
            return [headers, ...rows].map(row => 
                row.map(field => `"${String(field).replace(/"/g, '""')}"`).join(',')
            ).join('\n');
        }

        // Download CSV
        function downloadCSV(content, filename) {
            const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement('a');
            link.href = URL.createObjectURL(blob);
            link.download = filename;
            link.click();
        }

        // Utility functions
        function updateConnectionStatus(status) {
            const statusEl = document.getElementById('connectionStatus');
            statusEl.className = `connection-status ${status}`;
            statusEl.textContent = status === 'connected' ? '🟢 Connected' : 
                                  status === 'error' ? '🔴 Error' : '🟡 Connecting...';
        }

        function showLoading(show) {
            const tbody = document.getElementById('customerTableBody');
            if (show) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="19" style="text-align: center; padding: 40px; color: #666;">
                            <div class="loading"></div>
                            <div style="margin-top: 10px;">Loading customer data...</div>
                        </td>
                    </tr>
                `;
            }
        }

        function showUploadProgress(show) {
            const progressEl = document.getElementById('uploadProgress');
            const statusEl = document.getElementById('uploadStatus');
            
            if (show) {
                progressEl.style.display = 'block';
                statusEl.innerHTML = '<div class="loading"></div> Uploading file...';
            } else {
                progressEl.style.display = 'none';
            }
        }

        function updateUploadProgress(progress, message) {
            const progressBar = document.getElementById('progressBar');
            const statusEl = document.getElementById('uploadStatus');
            
            if (progressBar) {
                progressBar.style.width = `${progress}%`;
            }
            
            if (statusEl && message) {
                statusEl.textContent = message;
            }
        }

        function logActivity(message, type = 'info') {
            const timestamp = getCurrentISTTime();
            const logEntry = document.createElement('div');
            logEntry.style.cssText = `
                padding: 8px; margin: 5px 0; border-radius: 4px; font-size: 0.9em;
                background: ${type === 'error' ? '#fee' : '#f8f9fa'};
                color: ${type === 'error' ? '#c33' : '#333'};
                border-left: 3px solid ${type === 'error' ? '#dc3545' : '#667eea'};
            `;
            logEntry.innerHTML = `<strong>${timestamp} IST</strong> ${message}`;
            
            const activityLog = document.getElementById('activityLog');
            activityLog.insertBefore(logEntry, activityLog.firstChild);
            
            // Keep only last 50 entries
            while (activityLog.children.length > 50) {
                activityLog.removeChild(activityLog.lastChild);
            }
        }

        // Show toast notification
        function showToast(message, type = 'info', duration = 3000) {
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.textContent = message;
            
            document.body.appendChild(toast);
            
            // Show toast
            setTimeout(() => toast.classList.add('show'), 100);
            
            // Hide and remove toast
            setTimeout(() => {
                toast.classList.remove('show');
                setTimeout(() => document.body.removeChild(toast), 300);
            }, duration);
        }

        function setupAutoRefresh() {
            // Update status every 30 seconds
            refreshInterval = setInterval(function() {
                const refreshCount = parseInt(document.getElementById('statusRefreshCount').textContent.split(': ')[1] || '0');
                document.getElementById('statusRefreshCount').textContent = `Refreshes: ${refreshCount + 1}`;
                
                // Auto-refresh customer data every 5 minutes (300 seconds)
                if (refreshCount > 0 && refreshCount % 10 === 0) {
                    logActivity('🔄 Auto-refreshing customer data from database...');
                    loadCustomerData(false); // Silent refresh
                    
                    // Also refresh batch data every 5 minutes
                    loadBatchDetails();
                } else {
                    // Just update statistics and timestamp
                    document.getElementById('lastStatusUpdate').textContent = `Last update: ${getCurrentISTTime()} IST`;
                    updateStatistics();
                }
            }, 30000);
            
            // Initial data load
            logActivity('🚀 Starting initial data load from database...');
        }

        // Update customer call status
        function updateCustomerCallStatus(customerId, status, message) {
            const customer = customers.find(c => c.id === customerId);
            if (customer) {
                customer.call_status = status;
                renderCustomerTable();
                updateStatistics();
                logActivity(`Customer ${customer.full_name}: ${message || status}`);
            }
        }

        // Cleanup on page unload
        window.addEventListener('beforeunload', function() {
            if (refreshInterval) clearInterval(refreshInterval);
            if (ws) ws.close();
        });