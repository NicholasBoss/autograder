/**
 * Shared assignment loading functionality for Canvas Autograder
 */

class AssignmentLoader {
    constructor() {
        this.assignments = [];
        this.loading = false;
    }

    /**
     * Load assignments for a given course ID
     * @param {string} courseId - The Canvas course ID
     * @param {HTMLSelectElement} selectElement - The select element to populate
     * @param {HTMLElement} statusElement - Optional status element for messages
     * @returns {Promise<Array>} - Array of assignments
     */
    async loadAssignments(courseId, selectElement, statusElement = null) {
        if (!courseId || !selectElement) {
            console.error('AssignmentLoader: courseId and selectElement are required');
            return [];
        }

        if (this.loading) {
            console.log('AssignmentLoader: Already loading assignments');
            return [];
        }

        try {
            this.loading = true;
            selectElement.innerHTML = '<option value="">Loading assignments...</option>';
            selectElement.disabled = true;

            if (statusElement) {
                statusElement.innerHTML = '<div class="status-message loading">⏳ Loading assignments...</div>';
            }

            const response = await fetch(`/api/canvas/${courseId}/assignments`);

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            this.assignments = await response.json();

            selectElement.innerHTML = '<option value="">Select an assignment...</option>';

            if (this.assignments.length === 0) {
                selectElement.innerHTML = '<option value="">No assignments available</option>';
                if (statusElement) {
                    statusElement.innerHTML = '<div class="status-message error">No assignments found in this course.</div>';
                }
            } else {
                this.assignments.forEach(assignment => {
                    const option = document.createElement("option");
                    option.value = assignment.id;
                    option.textContent = assignment.name;
                    
                    // Add assignment details as data attributes
                    option.setAttribute('data-points', assignment.points_possible || 0);
                    option.setAttribute('data-due-date', assignment.due_at || '');
                    
                    selectElement.appendChild(option);
                });

                if (statusElement) {
                    statusElement.innerHTML = `<div class="status-message success">✅ Loaded ${this.assignments.length} assignments</div>`;
                }
            }

            selectElement.disabled = false;
            return this.assignments;

        } catch (error) {
            console.error("AssignmentLoader: Error loading assignments:", error);
            selectElement.innerHTML = '<option value="">Error loading assignments</option>';
            selectElement.disabled = false;
            
            if (statusElement) {
                statusElement.innerHTML = `<div class="status-message error">❌ Error loading assignments: ${error.message}</div>`;
            }
            
            return [];
        } finally {
            this.loading = false;
        }
    }

    /**
     * Get assignment details by ID
     * @param {string|number} assignmentId - The assignment ID
     * @returns {Object|null} - Assignment object or null if not found
     */
    getAssignmentById(assignmentId) {
        return this.assignments.find(assignment => assignment.id == assignmentId) || null;
    }

    /**
     * Reset the loader state
     */
    reset() {
        this.assignments = [];
        this.loading = false;
    }

    /**
     * Sync assignment dropdown with manual input
     * @param {HTMLSelectElement} selectElement - The select element
     * @param {HTMLInputElement} inputElement - The input element
     */
    syncWithInput(selectElement, inputElement) {
        if (!selectElement || !inputElement) return;

        // Sync from dropdown to input
        selectElement.addEventListener('change', () => {
            inputElement.value = selectElement.value;
        });

        // Sync from input to dropdown
        inputElement.addEventListener('input', () => {
            const value = inputElement.value.trim();
            if (value && !selectElement.disabled) {
                selectElement.value = value;
            }
        });
    }
}

// Create global instance
window.assignmentLoader = new AssignmentLoader();