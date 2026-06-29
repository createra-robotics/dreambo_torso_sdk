


const daemon = {
    currentStatus: {
        state: null,
    },

    start: async (wakeUp) => {
        await fetch(`/api/daemon/start?wake_up=${wakeUp}`, {
            method: 'POST',
        })
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(async (data) => {
                await daemon.checkStatusUpdate();
            })
            .catch((error) => {
                console.error('Error starting daemon:', error);
            });
    },

    stop: async (gotoSleep) => {
        await fetch(`/api/daemon/stop?goto_sleep=${gotoSleep}`, {
            method: 'POST',
        })
            .then((response) => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(async (data) => {
                await daemon.checkStatusUpdate();
            })
            .catch((error) => {
                console.error('Error stopping daemon:', error);
            });
    },

    getStatus: async () => {
        await fetch('/api/daemon/status')
            .then((response) => response.json())
            .then(async (data) => {
                let currentState = daemon.currentStatus.state;
                let newState = data.state || null;

                daemon.currentStatus = data;

                if (currentState === null || currentState !== newState) {
                    await daemon.updateUI();
                }

            })
            .catch((error) => {
                console.error('Error fetching daemon status:', error);
            });
    },

    checkStatusUpdate: async (initialState) => {
        await daemon.getStatus();

        if (!initialState) {
            initialState = daemon.currentStatus.state;
        }

        let currentState = daemon.currentStatus.state;

        if (currentState !== "error" && (currentState === initialState || currentState === "starting" || currentState === "stopping")) {
            setTimeout(() => {
                daemon.checkStatusUpdate(initialState);
            }, 500);
        }
    },

    toggleSwitch: async () => {
        const toggleDaemonSwitch = document.getElementById('daemon-toggle');

        if (toggleDaemonSwitch.checked) {
            console.log('Toggle switched ON. Starting daemon...');
            await daemon.start(true);
        } else {
            console.log('Toggle switched OFF. Stopping daemon...');
            await daemon.stop(true);
        }

        await daemon.updateToggle();
    },

    updateUI: async () => {
        const toggleDaemonSwitch = document.getElementById('daemon-toggle');
        const backendStatusIcon = document.getElementById('backend-status-icon');
        const backendStatusText = document.getElementById('backend-status-text');
        const stateWord = document.getElementById('daemon-state-word');
        const telemetryState = document.getElementById('telemetry-state');

        let daemonState = daemon.currentStatus.state;

        // Apply readout: { word, sub, led(class), checked, disabled }
        const setReadout = (word, sub, led, checked, disabled) => {
            toggleDaemonSwitch.disabled = !!disabled;
            toggleDaemonSwitch.checked = !!checked;
            backendStatusIcon.classList.remove('is-online', 'is-warn', 'is-fault');
            if (led) backendStatusIcon.classList.add(led);
            if (stateWord) stateWord.textContent = word;
            if (backendStatusText) backendStatusText.textContent = sub;
            if (telemetryState) telemetryState.textContent = (daemonState || 'unknown').toUpperCase();
        };

        toggleDaemonSwitch.disabled = false;

        if (daemonState === 'starting') {
            setReadout('WAKING', 'Waking up…', 'is-warn', true, true);
        }
        else if (daemonState === 'running') {
            setReadout('ONLINE', 'Up and ready', 'is-online', true, false);
        }
        else if (daemonState === 'stopping') {
            setReadout('SLEEPING', 'Going to sleep…', 'is-warn', false, true);
        }
        else if (daemonState === 'stopped' || daemonState === 'not_initialized') {
            setReadout('STANDBY', 'Powered down', null, false, false);
        }
        else if (daemonState === 'error') {
            setReadout('FAULT', 'Error occurred', 'is-fault', false, false);
            notificationCenter.showError(daemon.currentStatus.error);
        }

        await daemon.updateToggle();
    },

    updateToggle: async () => {
        const toggle = document.getElementById('daemon-toggle');
        const toggleSlider = document.getElementById('daemon-toggle-slider');
        const toggleOnLabel = document.getElementById('daemon-toggle-on');
        const toggleOffLabel = document.getElementById('daemon-toggle-off');

        toggleSlider.classList.remove('hidden');

        if (toggle.checked) {
            toggleOnLabel.classList.remove('hidden');
            toggleOffLabel.classList.add('hidden');
        } else {
            toggleOnLabel.classList.add('hidden');
            toggleOffLabel.classList.remove('hidden');
        }
    },
};


window.addEventListener('load', async () => {
    document.getElementById('daemon-toggle').onchange = daemon.toggleSwitch;
    await daemon.getStatus();
});