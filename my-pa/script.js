document.addEventListener('DOMContentLoaded', function() {
    const commandsList = document.getElementById('commands-list');
    const commands = [
        'list_files',
        'read_file',
        'write_file',
        'create_directory',
        'move_path',
        'delete_path',
        'edit_file',
        'search_files',
        'run_command',
        'web_search',
        'encyclopedia_search',
        'fetch_url'
    ];

    commands.forEach(command => {
        const li = document.createElement('li');
        li.textContent = command;
        commandsList.appendChild(li);
    });
});