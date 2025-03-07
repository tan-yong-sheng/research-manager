// API endpoint
const API_URL = 'http://localhost:8000';

// Global variables
let allFolders = [];
let currentFolderId = null;

// Initialize Select2 for tags
$(document).ready(() => {
    $('#tags').select2({
        tags: true,
        tokenSeparators: [',', ' '],
        placeholder: 'Add tags...'
    });
    
    // Load both papers and folders when the app starts
    Promise.all([loadFolders(), loadDashboard()]);

    // Add click event listeners for navigation
    $("a.nav-link").click(function(e) {
        e.preventDefault(); // Prevent default anchor behavior
        const action = $(this).text().trim();
        if (action === "Dashboard") {
            showDashboard();
        } else if (action === "Upload Paper") {
            showUploadForm();
        }
    });

    // Set up the folder form submission
    $('#folderForm').submit(function(e) {
        e.preventDefault();
        saveFolder();
    });

    // Set up the move paper form submission
    $('#movePaperForm').submit(function(e) {
        e.preventDefault();
        movePaper();
    });
});

// Navigation functions
function showDashboard() {
    console.log("Showing dashboard");
    $('#dashboard').show();
    $('#uploadForm').hide();
    loadDashboard();
}

function showUploadForm() {
    console.log("Showing upload form");
    $('#dashboard').hide();
    $('#uploadForm').show();
    loadTags();
    updateFolderSelects();
}

// Folder Functions
async function loadFolders() {
    try {
        const response = await fetch(`${API_URL}/folders/`);
        if (!response.ok) {
            throw new Error("Failed to load folders");
        }
        
        const data = await response.json();
        allFolders = data.folders || [];
        
        // Add Default Library if it doesn't exist
        if (!allFolders.find(f => f.id === 'default')) {
            allFolders.unshift({
                id: 'default',
                name: 'Default Library',
                parent_id: null,
                description: 'Default folder for papers'
            });
        }
        
        renderFolderTree();
        updateFolderSelects();
        
        return data;
    } catch (error) {
        console.error('Error loading folders:', error);
    }
}

function renderFolderTree() {
    const container = $('#foldersContainer');
    container.empty();
    
    // Always show Default Library first
    const defaultLibrary = allFolders.find(f => f.id === 'default');
    if (defaultLibrary) {
        container.append(renderFolder(defaultLibrary));
    }
    
    // Find root level folders (no parent)
    const rootFolders = allFolders.filter(folder => !folder.parent_id && folder.id !== 'default');
    
    // Render each root folder and its children
    rootFolders.forEach(folder => {
        container.append(renderFolder(folder));
    });
}

function renderFolder(folder, isNested = false) {
    // Find children of this folder
    const children = allFolders.filter(f => f.parent_id === folder.id);
    const hasChildren = children.length > 0;
    
    const folderHtml = $(`
        <div class="folder-container" data-id="${folder.id}">
            <div class="folder-item d-flex justify-content-between align-items-center" 
                 data-id="${folder.id}"
                 ondragover="handleDragOver(event)"
                 ondragleave="handleDragLeave(event)"
                 ondrop="handleDrop(event, '${folder.id}')">
                <div onclick="openFolder('${folder.id}')" style="flex-grow: 1;">
                    ${hasChildren ? 
                      `<i class="bi bi-caret-right folder-toggle" onclick="toggleFolderChildren(event, '${folder.id}')"></i>` : 
                      `<i class="bi bi-dash folder-toggle invisible"></i>`}
                    <i class="bi bi-folder"></i>
                    <span class="folder-name">${folder.name}</span>
                </div>
                <div class="folder-actions">
                    <i class="bi bi-pencil-square mx-1" onclick="editFolder(event, '${folder.id}')"></i>
                    <i class="bi bi-trash mx-1" onclick="deleteFolder(event, '${folder.id}')"></i>
                </div>
            </div>
            ${hasChildren ? 
              `<div class="nested-folders" id="children-${folder.id}" style="display: none;"></div>` : 
              ''}
        </div>
    `);
    
    // Recursively add children
    if (hasChildren) {
        const childrenContainer = folderHtml.find(`#children-${folder.id}`);
        children.forEach(child => {
            childrenContainer.append(renderFolder(child, true));
        });
    }
    
    return folderHtml;
}

function toggleFolderChildren(event, folderId) {
    event.stopPropagation();
    const childrenContainer = $(`#children-${folderId}`);
    const toggleIcon = $(event.target);
    
    if (childrenContainer.is(':visible')) {
        childrenContainer.hide();
        toggleIcon.removeClass('bi-caret-down').addClass('bi-caret-right');
    } else {
        childrenContainer.show();
        toggleIcon.removeClass('bi-caret-right').addClass('bi-caret-down');
    }
}

function openFolder(folderId) {
    // Set active folder
    $('.folder-item').removeClass('active');
    $(`.folder-item[data-id="${folderId}"]`).addClass('active');
    
    currentFolderId = folderId;
    
    // Find the folder name
    const folder = allFolders.find(f => f.id === folderId);
    $('#currentViewTitle').text(folder ? folder.name : 'All Papers');
    
    // Load papers in this folder
    loadPapersInFolder(folderId);
}

function showAllPapers() {
    // Reset active folder
    $('.folder-item').removeClass('active');
    $('#allPapersFolder').addClass('active');
    
    currentFolderId = null;
    $('#currentViewTitle').text('All Papers');
    
    // Load all papers
    loadDashboard();
}

async function loadPapersInFolder(folderId) {
    try {
        const response = await fetch(`${API_URL}/papers/by-folder/${folderId}`);
        if (!response.ok) {
            throw new Error("Failed to load papers in folder");
        }
        
        const data = await response.json();
        updatePapersList(data.papers);
    } catch (error) {
        console.error('Error loading papers in folder:', error);
    }
}

function showCreateFolderModal() {
    // Reset the form
    $('#folderForm')[0].reset();
    $('#folderId').val('');
    $('#folderModalTitle').text('Create New Folder');
    
    // Update parent folder select
    updateParentFolderSelect();
    
    // Show the modal
    new bootstrap.Modal('#folderModal').show();
}

function editFolder(event, folderId) {
    event.stopPropagation();
    
    // Find the folder data
    const folder = allFolders.find(f => f.id === folderId);
    if (!folder) return;
    
    // Fill the form
    $('#folderId').val(folder.id);
    $('#folderName').val(folder.name);
    $('#folderDescription').val(folder.description);
    $('#folderModalTitle').text('Edit Folder');
    
    // Update parent folder select, excluding self and children
    updateParentFolderSelect(folderId);
    $('#parentFolder').val(folder.parent_id || '');
    
    // Show the modal
    new bootstrap.Modal('#folderModal').show();
}

function updateParentFolderSelect(excludeFolderId = null) {
    const select = $('#parentFolder');
    select.find('option:not(:first)').remove();
    
    // Function to check if a folder is a child of another
    function isChildOf(childId, parentId) {
        if (childId === parentId) return true;
        
        const folder = allFolders.find(f => f.id === childId);
        if (!folder || !folder.parent_id) return false;
        
        return isChildOf(folder.parent_id, parentId);
    }
    
    // Add all folders except the one being edited and its children
    allFolders.forEach(folder => {
        if (!excludeFolderId || !isChildOf(folder.id, excludeFolderId)) {
            select.append(`<option value="${folder.id}">${folder.name}</option>`);
        }
    });
}

function updateFolderSelects() {
    // Update folder selects in forms
    const selects = ['#folderSelect', '#movePaperFolder'];
    
    selects.forEach(selector => {
        const select = $(selector);
        select.find('option:not(:first)').remove(); // Keep the Default Library option
        
        // Add all folders except Default Library (since it's already the first option)
        allFolders
            .filter(folder => folder.id !== 'default')
            .forEach(folder => {
                select.append(`<option value="${folder.id}">${folder.name}</option>`);
            });
    });
}

async function saveFolder() {
    const folderId = $('#folderId').val();
    const isNew = !folderId;
    
    const folderData = {
        name: $('#folderName').val(),
        parent_id: $('#parentFolder').val() || null,
        description: $('#folderDescription').val() || ""
    };
    
    try {
        let response;
        
        if (isNew) {
            // Create new folder
            response = await fetch(`${API_URL}/folders/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(folderData)
            });
        } else {
            // Update existing folder
            response = await fetch(`${API_URL}/folders/${folderId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(folderData)
            });
        }
        
        if (!response.ok) {
            throw new Error(isNew ? "Failed to create folder" : "Failed to update folder");
        }
        
        // Reload folders
        await loadFolders();
        
        // Close the modal
        bootstrap.Modal.getInstance('#folderModal').hide();
        
        // Show success message
        alert(isNew ? "Folder created successfully" : "Folder updated successfully");
    } catch (error) {
        console.error('Error saving folder:', error);
        alert('Failed to save folder: ' + error.message);
    }
}

async function deleteFolder(event, folderId) {
    event.stopPropagation();
    
    if (!confirm("Are you sure you want to delete this folder? Papers inside will be moved to no folder.")) {
        return;
    }
    
    try {
        const response = await fetch(`${API_URL}/folders/${folderId}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            throw new Error("Failed to delete folder");
        }
        
        // Reload folders
        await loadFolders();
        
        // If deleted folder was current folder, show all papers
        if (currentFolderId === folderId) {
            showAllPapers();
        }
        
        // Show success message
        alert("Folder deleted successfully");
    } catch (error) {
        console.error('Error deleting folder:', error);
        alert('Failed to delete folder: ' + error.message);
    }
}

function showMovePaperModal(filename) {
    $('#movePaperFilename').val(filename);
    updateFolderSelects();
    new bootstrap.Modal('#movePaperModal').show();
}

async function movePaper() {
    const filename = $('#movePaperFilename').val();
    const folderId = $('#movePaperFolder').val() || null;
    
    console.log("Moving paper:", filename, "to folder:", folderId);
    
    try {
        // Construct URL with folder_id as a query parameter
        let url = `${API_URL}/papers/${filename}/move`;
        if (folderId !== null) {
            url += `?folder_id=${folderId}`;
        }
        
        console.log("Request URL:", url);
        
        const response = await fetch(url, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (!response.ok) {
            const errorData = await response.text();
            console.error("Server response:", errorData);
            throw new Error(`Failed to move paper: ${errorData}`);
        }
        
        // Close the modal
        bootstrap.Modal.getInstance('#movePaperModal').hide();
        
        // Refresh the current view
        if (currentFolderId) {
            loadPapersInFolder(currentFolderId);
        } else {
            loadDashboard();
        }
        
        // Show success message
        alert("Paper moved successfully");
    } catch (error) {
        console.error('Error moving paper:', error);
        alert('Failed to move paper: ' + error.message);
    }
}

// Drag and drop functions
function handleDragOver(event) {
    event.preventDefault();
    $(event.currentTarget).addClass('drag-over');
}

function handleDragLeave(event) {
    $(event.currentTarget).removeClass('drag-over');
}

function handleDrop(event, folderId) {
    event.preventDefault();
    $(event.currentTarget).removeClass('drag-over');
    
    const filename = event.dataTransfer.getData("text");
    if (filename) {
        movePaperToFolder(filename, folderId);
    }
}

async function movePaperToFolder(filename, folderId) {
    try {
        // Construct URL with folder_id as a query parameter
        let url = `${API_URL}/papers/${filename}/move`;
        if (folderId !== null) {
            url += `?folder_id=${folderId}`;
        }
        
        const response = await fetch(url, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (!response.ok) {
            throw new Error("Failed to move paper");
        }
        
        // Refresh the current view
        if (currentFolderId) {
            loadPapersInFolder(currentFolderId);
        } else {
            loadDashboard();
        }
    } catch (error) {
        console.error('Error moving paper:', error);
        alert('Failed to move paper: ' + error.message);
    }
}

// Load dashboard data
async function loadDashboard() {
    try {
        const [statsResponse, papersResponse] = await Promise.all([
            fetch(`${API_URL}/stats`),
            fetch(`${API_URL}/papers/`)
        ]);
        
        if (!statsResponse.ok || !papersResponse.ok) {
            throw new Error("Failed to fetch data");
        }
        
        const stats = await statsResponse.json();
        const papers = await papersResponse.json();
        
        console.log("Dashboard data loaded:", { stats, papers });
        
        updateStats(stats);
        updatePapersList(papers.papers);
        updateFilters(stats);
    } catch (error) {
        console.error('Error loading dashboard:', error);
        // Continue showing the page with empty data rather than alerting
    }
}

// Update statistics
function updateStats(stats) {
    $('#totalPapers').text(stats.total_papers);
    $('#totalCategories').text(Object.keys(stats.categories).length);
    $('#totalTags').text(stats.tags.length);
    
    const years = Object.keys(stats.years).map(Number).sort();
    if (years.length > 0) {
        $('#yearsSpan').text(`${Math.min(...years)} - ${Math.max(...years)}`);
    }
}

// Update papers list
function updatePapersList(papers) {
    const papersList = $('#papersList');
    papersList.empty();
    
    if (!papers || papers.length === 0) {
        papersList.append('<div class="col-12"><p class="text-muted">No papers found</p></div>');
        return;
    }
    
    papers.forEach(paper => {
        // Parse tags if they're stored as JSON string
        let tags = [];
        if (typeof paper.tags === 'string') {
            try {
                tags = JSON.parse(paper.tags);
            } catch (e) {
                console.warn('Error parsing tags:', e);
            }
        } else if (Array.isArray(paper.tags)) {
            tags = paper.tags;
        }
        
        const card = $(`
            <div class="col-md-4 mb-4">
                <div class="card paper-card h-100" draggable="true" ondragstart="event.dataTransfer.setData('text', '${paper.filename}')">
                    <div class="card-body">
                        <h5 class="card-title">${paper.title || paper.filename}</h5>
                        <p class="card-text">
                            <small class="text-muted">${paper.authors || ''}</small><br>
                            <small class="text-muted">${paper.year || 'Year not specified'}</small>
                        </p>
                        ${tags.map(tag => `<span class="badge bg-secondary me-1">${tag}</span>`).join('')}
                        ${paper.category ? `<span class="badge bg-primary">${paper.category}</span>` : ''}
                        
                        ${paper.folder_id ? `
                        <br><small class="mt-2 d-block">
                            <i class="bi bi-folder-fill"></i> ${getFolderName(paper.folder_id)}
                        </small>` : ''}
                    </div>
                    <div class="card-footer">
                        <button class="btn btn-sm btn-primary" onclick="viewPaper('${paper.filename}')">View</button>
                        <button class="btn btn-sm btn-secondary" onclick="editMetadata('${paper.filename}')">Edit</button>
                        <button class="btn btn-sm btn-info" onclick="showMovePaperModal('${paper.filename}')">Move</button>
                        <button class="btn btn-sm btn-danger" onclick="deletePaper('${paper.filename}')">Delete</button>
                    </div>
                </div>
            </div>
        `);
        
        papersList.append(card);
    });
}

function getFolderName(folderId) {
    const folder = allFolders.find(f => f.id === folderId);
    return folder ? folder.name : 'Unknown folder';
}

// Update filters
function updateFilters(stats) {
    const categorySelect = $('#categoryFilter');
    const tagSelect = $('#tagFilter');
    
    categorySelect.empty().append('<option value="">All Categories</option>');
    Object.keys(stats.categories).forEach(category => {
        categorySelect.append(`<option value="${category}">${category} (${stats.categories[category]})</option>`);
    });
    
    tagSelect.empty().append('<option value="">All Tags</option>');
    stats.tags.forEach(tag => {
        tagSelect.append(`<option value="${tag}">${tag}</option>`);
    });
}

// Load existing tags for the upload form
async function loadTags() {
    try {
        const response = await fetch(`${API_URL}/stats`);
        const stats = await response.json();
        
        const tagsSelect = $('#tags');
        tagsSelect.empty();
        stats.tags.forEach(tag => {
            tagsSelect.append(new Option(tag, tag));
        });
    } catch (error) {
        console.error('Error loading tags:', error);
    }
}

// Handle paper upload
$('#paperUploadForm').submit(async function(e) {
    e.preventDefault();
    
    const files = $('#pdfFile')[0].files;
    const folderId = $('#uploadFolderId').val();
    
    // Handle multiple files (folder upload)
    if (files.length > 1) {
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            if (file.type === 'application/pdf') {
                await uploadSingleFile(file, folderId);
            }
        }
    } else {
        // Single file upload
        await uploadSingleFile(files[0], folderId);
    }
    
    // Close modal and refresh view
    bootstrap.Modal.getInstance('#uploadModal').hide();
    if (currentFolderId) {
        loadPapersInFolder(currentFolderId);
    } else {
        loadDashboard();
    }
});

async function uploadSingleFile(file, folderId) {
    const formData = new FormData();
    formData.append('file', file);
    
    const metadata = {
        title: $('#title').val() || file.name,
        authors: $('#authors').val(),
        year: $('#year').val() ? parseInt($('#year').val()) : null,
        category: $('#category').val() || null,
        tags: $('#tags').val() || [],
        abstract: $('#abstract').val() || ""
    };
    
    formData.append('metadata', JSON.stringify(metadata));
    
    // Add folder_id
    if (folderId) {
        formData.append('folder_id', folderId);
    }
    
    try {
        const response = await fetch(`${API_URL}/papers/`, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Upload failed');
        }
    } catch (error) {
        console.error('Error uploading file:', error);
        alert(`Failed to upload ${file.name}: ${error.message}`);
    }
}

// View paper
async function viewPaper(filename) {
    window.open(`${API_URL}/papers/${filename}`, '_blank');
}

// Edit metadata
async function editMetadata(filename) {
    try {
        console.log('Fetching paper details for:', filename);
        const response = await fetch(`${API_URL}/papers/${filename}/metadata`);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error('Server response:', response.status, errorText);
            throw new Error(`Server returned ${response.status}: ${errorText}`);
        }
        
        const paper = await response.json();
        console.log('Received paper data:', paper);
        
        // Parse tags if they're stored as JSON string
        let tags = [];
        if (typeof paper.tags === 'string') {
            try {
                tags = JSON.parse(paper.tags);
            } catch (e) {
                console.warn('Error parsing tags:', e);
            }
        } else if (Array.isArray(paper.tags)) {
            tags = paper.tags;
        }
        
        // Populate modal with paper details
        $('#paperTitle').text(paper.title || filename);
        
        // Update the folder options
        updateFolderSelects();
        
        // Add form for editing metadata
        $('#paperDetails').html(`
            <form id="editMetadataForm">
                <input type="hidden" id="editFilename" value="${filename}">
                <div class="mb-3">
                    <label class="form-label">Title</label>
                    <input type="text" class="form-control" id="editTitle" value="${paper.title || ''}">
                </div>
                <div class="mb-3">
                    <label class="form-label">Authors</label>
                    <input type="text" class="form-control" id="editAuthors" value="${paper.authors || ''}">
                </div>
                <div class="mb-3">
                    <label class="form-label">Year</label>
                    <input type="number" class="form-control" id="editYear" value="${paper.year || ''}">
                </div>
                <div class="mb-3">
                    <label class="form-label">Folder</label>
                    <select class="form-control" id="editFolder">
                        <option value="">No folder</option>
                        ${allFolders.map(folder => 
                            `<option value="${folder.id}" ${paper.folder_id === folder.id ? 'selected' : ''}>
                                ${folder.name}
                            </option>`
                        ).join('')}
                    </select>
                </div>
                <div class="mb-3">
                    <label class="form-label">Category</label>
                    <input type="text" class="form-control" id="editCategory" value="${paper.category || ''}">
                </div>
                <div class="mb-3">
                    <label class="form-label">Tags</label>
                    <select class="form-control" id="editTags" multiple>
                        ${tags.map(tag => `<option value="${tag}" selected>${tag}</option>`).join('')}
                    </select>
                </div>
                <div class="mb-3">
                    <label class="form-label">Abstract</label>
                    <textarea class="form-control" id="editAbstract" rows="3">${paper.abstract || ''}</textarea>
                </div>
                <button type="submit" class="btn btn-primary">Save Changes</button>
            </form>
        `);
        
        // Initialize Select2 for tags in modal
        $('#editTags').select2({
            tags: true,
            tokenSeparators: [',', ' ']
        });
        
        // Set up form submission handler
        $('#editMetadataForm').submit(async function(e) {
            e.preventDefault();
            
            const updatedMetadata = {
                title: $('#editTitle').val(),
                authors: $('#editAuthors').val(),
                year: $('#editYear').val() ? parseInt($('#editYear').val()) : null,
                category: $('#editCategory').val() || null,
                tags: $('#editTags').val() || [],
                abstract: $('#editAbstract').val() || "",
                folder_id: $('#editFolder').val() || null
            };
            
            try {
                const response = await fetch(`${API_URL}/papers/${filename}/metadata`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(updatedMetadata)
                });
                
                if (!response.ok) {
                    const errorData = await response.text();
                    console.error('Update response:', response.status, errorData);
                    throw new Error(`Update failed: ${errorData}`);
                }
                
                alert('Metadata updated successfully');
                bootstrap.Modal.getInstance('#paperDetailsModal').hide();
                
                // Refresh the current view
                if (currentFolderId) {
                    loadPapersInFolder(currentFolderId);
                } else {
                    loadDashboard();
                }
            } catch (error) {
                console.error('Error updating metadata:', error);
                alert('Failed to update metadata: ' + error.message);
            }
        });
        
        // Show modal
        new bootstrap.Modal('#paperDetailsModal').show();
    } catch (error) {
        console.error('Error loading paper details:', error);
        alert('Failed to load paper details: ' + error.message);
    }
}

// Delete paper
async function deletePaper(filename) {
    if (!confirm('Are you sure you want to delete this paper?')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_URL}/papers/${filename}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            alert('Paper deleted successfully');
            
            // Refresh the current view
            if (currentFolderId) {
                loadPapersInFolder(currentFolderId);
            } else {
                loadDashboard();
            }
        } else {
            throw new Error('Delete failed');
        }
    } catch (error) {
        console.error('Error deleting paper:', error);
        alert('Failed to delete paper');
    }
}

// Search functionality
$('#searchInput').on('input', function() {
    const query = $(this).val();
    if (query.length >= 3) {
        searchPapers(query);
    } else if (query.length === 0) {
        // Refresh the current view
        if (currentFolderId) {
            loadPapersInFolder(currentFolderId);
        } else {
            loadDashboard();
        }
    }
});

async function searchPapers(query) {
    try {
        const response = await fetch(`${API_URL}/search/?query=${encodeURIComponent(query)}`);
        const results = await response.json();
        updatePapersList(results.results.map(r => r.metadata));
    } catch (error) {
        console.error('Error searching papers:', error);
    }
}

// Filter handlers
$('#categoryFilter').change(function() {
    const category = $(this).val();
    if (category) {
        filterByCategory(category);
    } else {
        // Refresh the current view
        if (currentFolderId) {
            loadPapersInFolder(currentFolderId);
        } else {
            loadDashboard();
        }
    }
});

$('#tagFilter').change(function() {
    const tag = $(this).val();
    if (tag) {
        filterByTag(tag);
    } else {
        // Refresh the current view
        if (currentFolderId) {
            loadPapersInFolder(currentFolderId);
        } else {
            loadDashboard();
        }
    }
});

async function filterByCategory(category) {
    try {
        const response = await fetch(`${API_URL}/papers/by-category/${encodeURIComponent(category)}`);
        const results = await response.json();
        updatePapersList(results.papers);
    } catch (error) {
        console.error('Error filtering by category:', error);
    }
}

async function filterByTag(tag) {
    try {
        const response = await fetch(`${API_URL}/papers/by-tag/${encodeURIComponent(tag)}`);
        const results = await response.json();
        updatePapersList(results.papers);
    } catch (error) {
        console.error('Error filtering by tag:', error);
    }
}

// Upload handling functions
function handleFileUpload() {
    // Set file input for single file upload
    $('#pdfFile').removeAttr('webkitdirectory');
    $('#pdfFile').removeAttr('directory');
    $('#pdfFile').removeAttr('multiple');
    
    // Clear the form
    $('#paperUploadForm')[0].reset();
    $('#uploadFolderId').val(currentFolderId || 'default');
    
    // Show upload form directly in the dashboard
    $('#uploadForm').show();
    $('#dashboard').hide();
}

function handleFolderUpload() {
    // Set file input for folder upload
    $('#pdfFile').attr('webkitdirectory', '');
    $('#pdfFile').attr('directory', '');
    $('#pdfFile').attr('multiple', '');
    
    // Clear the form
    $('#paperUploadForm')[0].reset();
    $('#uploadFolderId').val(currentFolderId || 'default');
    
    // Show upload form directly in the dashboard
    $('#uploadForm').show();
    $('#dashboard').hide();
}