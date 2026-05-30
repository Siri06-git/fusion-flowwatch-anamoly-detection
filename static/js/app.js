// FlowWatch App Logic (Phase 1)
console.log("FlowWatch Portal loaded successfully.");

document.addEventListener('DOMContentLoaded', () => {
    // Dynamic table filtering by student ID on the analytics page
    const searchInput = document.getElementById('student-search');
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            const query = searchInput.value.trim().toLowerCase();
            const rows = document.querySelectorAll('#student-table-body tr');
            rows.forEach(row => {
                const badge = row.querySelector('.student-id-badge');
                if (badge) {
                    const studentId = badge.textContent.trim().toLowerCase();
                    if (studentId.includes(query)) {
                        row.style.display = '';
                    } else {
                        row.style.display = 'none';
                    }
                }
            });
        });
    }
});
