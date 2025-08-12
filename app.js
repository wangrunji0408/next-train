class NextTrainApp {
    constructor() {
        this.data = null;
        this.userLocation = null;
        this.nearestStation = null;
        this.selectedLine = null;
        this.selectedDirection = null;
        this.countdownInterval = null;

        this.loadingEl = document.getElementById('loading');
        this.errorEl = document.getElementById('error');
        this.appEl = document.getElementById('app');
        this.stationNameEl = document.getElementById('stationName');
        this.distanceEl = document.getElementById('distance');
        this.lineSelectorEl = document.getElementById('lineSelector');
        this.directionSelectorEl = document.getElementById('directionSelector');
        this.trainTimeEl = document.getElementById('trainTime');
        this.countdownEl = document.getElementById('countdown');
        this.trainInfoEl = document.getElementById('trainInfo');
        this.sortByDistanceBtnEl = document.getElementById('sortByDistanceBtn');
        this.inputStationBtnEl = document.getElementById('inputStationBtn');
        this.languageSelectorEl = document.getElementById('languageSelector');
        this.currentLanguageEl = document.getElementById('currentLanguage');

        this.setupLanguageSelector();
        this.init();
    }

    formatLineName(route) {
        if (/^\d+$/.test(route)) {
            // Numeric route (e.g., "1" -> "1号线" or "Line 1")
            return window.i18n.t('lineNameNumeric', { number: route });
        } else {
            // Non-numeric route (e.g., "昌平线" -> "昌平线" or "Changping Line")
            return window.i18n.t('lineNameNonNumeric', { name: route });
        }
    }

    mergeData(routesData, schedules) {
        // Get all unique stations from schedules
        const allStationNames = new Set();
        schedules.forEach(schedule => allStationNames.add(schedule.station));

        const stationsWithSchedules = Array.from(allStationNames).map(stationName => {
            // Get coordinates from routes.json if available
            const coordinates = routesData.coordinates[stationName];
            const lat = coordinates ? coordinates[0] : 39.9042; // Default Beijing center
            const lng = coordinates ? coordinates[1] : 116.4074;

            // Get schedules for this station
            const stationSchedules = schedules.filter(schedule =>
                schedule.station === stationName
            );

            // Group by route/line
            const uniqueRoutes = [...new Set(stationSchedules.map(s => s.route))];
            const lines = uniqueRoutes.map(route => {
                const lineName = this.formatLineName(route);
                // Find the line by matching the route number with the lineName in routes.json
                const line = routesData.lines.find(l => l.lineName === route);
                const lineSchedules = stationSchedules.filter(schedule =>
                    schedule.route === route
                );

                const directions = this.groupSchedulesByDirection(lineSchedules);

                return {
                    lineName,
                    route, // Store original route for formatting
                    lineColor: line ? line.lineColor : '#999999', // Default color for unknown lines
                    directions
                };
            });

            return {
                name: stationName,
                lat,
                lng,
                lines
            };
        });

        return { stations: stationsWithSchedules };
    }

    groupSchedulesByDirection(schedules) {
        const directions = new Map();

        schedules.forEach(schedule => {
            const direction = schedule.destination;
            if (!directions.has(direction)) {
                directions.set(direction, {
                    direction,
                    schedule: {
                        weekday: {
                            times: []
                        }
                    }
                });
            }

            const directionData = directions.get(direction);
            if (schedule.operating_time === '工作日') {
                directionData.schedule.weekday.times = schedule.schedule_times;
            }
        });

        return Array.from(directions.values());
    }

    setupLanguageSelector() {
        // Set up language selector - direct toggle between zh and en
        this.languageSelectorEl.addEventListener('click', () => {
            const currentLang = window.i18n.getCurrentLanguage();
            const newLang = currentLang === 'zh' ? 'en' : 'zh';
            window.i18n.setLanguage(newLang);
        });

        // Listen for language changes
        window.addEventListener('languageChanged', () => {
            this.updateLanguageDisplay();
            this.translateUI();
        });

        // Initial language setup
        this.updateLanguageDisplay();
        this.translateUI();
    }

    updateLanguageDisplay() {
        const currentLang = window.i18n.getCurrentLanguage();
        const langMap = {
            'zh': '🌐 中文',
            'en': '🌐 English'
        };
        this.currentLanguageEl.textContent = langMap[currentLang];
    }

    translateUI() {
        // Translate elements with data-i18n attribute
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            el.textContent = window.i18n.t(key);
        });

        // Translate title attributes
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            el.setAttribute('title', window.i18n.t(key));
        });

        // Update dynamic content if app is running
        if (this.nearestStation) {
            this.updateStationDisplay();
            this.renderLineSelector();
            this.renderDirectionSelector();
            this.updateTrainInfo();
        }
    }

    async init() {
        try {
            await this.loadData();
            try {
                await this.getUserLocation();
            } catch (locationError) {
                this.showLocationFallback();
                return;
            }
            this.findNearestStation();
            this.setupUI();
            this.startCountdown();
        } catch (error) {
            this.showError(error.message);
        }
    }

    async loadData() {
        try {
            const [routesResponse, schedulesResponse] = await Promise.all([
                fetch('data/routes.json'),
                fetch('data/timetable.jsonl')
            ]);

            if (!routesResponse.ok || !schedulesResponse.ok) {
                throw new Error(window.i18n.t('cannotLoadData'));
            }

            const routesData = await routesResponse.json();
            const schedulesText = await schedulesResponse.text();

            // Parse JSONL format
            const schedules = schedulesText.trim().split('\n')
                .filter(line => line.trim())
                .map(line => JSON.parse(line));

            this.data = this.mergeData(routesData, schedules);
        } catch (error) {
            throw new Error(window.i18n.t('dataLoadFailed'));
        }
    }

    async getUserLocation() {
        return new Promise((resolve, reject) => {
            if (!navigator.geolocation) {
                reject(new Error(window.i18n.t('locationNotSupported')));
                return;
            }

            navigator.geolocation.getCurrentPosition(
                (position) => {
                    this.userLocation = {
                        lat: position.coords.latitude,
                        lng: position.coords.longitude
                    };
                    resolve();
                },
                (error) => {
                    let message = window.i18n.t('locationFailed');
                    switch (error.code) {
                        case error.PERMISSION_DENIED:
                            message = window.i18n.t('locationPermissionDenied');
                            break;
                        case error.POSITION_UNAVAILABLE:
                            message = window.i18n.t('locationUnavailable');
                            break;
                        case error.TIMEOUT:
                            message = window.i18n.t('locationTimeout');
                            break;
                    }
                    reject(new Error(message));
                },
                {
                    enableHighAccuracy: true,
                    timeout: 10000,
                    maximumAge: 300000
                }
            );
        });
    }

    calculateDistance(lat1, lng1, lat2, lng2) {
        const R = 6371;
        const dLat = this.toRad(lat2 - lat1);
        const dLng = this.toRad(lng2 - lng1);
        const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(this.toRad(lat1)) * Math.cos(this.toRad(lat2)) *
            Math.sin(dLng / 2) * Math.sin(dLng / 2);
        const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
        return R * c;
    }

    toRad(value) {
        return value * Math.PI / 180;
    }

    findNearestStation() {
        let minDistance = Infinity;
        let nearest = null;

        this.data.stations.forEach(station => {
            const distance = this.calculateDistance(
                this.userLocation.lat,
                this.userLocation.lng,
                station.lat,
                station.lng
            );

            if (distance < minDistance) {
                minDistance = distance;
                nearest = { ...station, distance };
            }
        });

        this.nearestStation = nearest;
        this.selectedLine = nearest.lines[0];
        this.selectedDirection = nearest.lines[0].directions[0];
    }

    setupUI() {
        this.loadingEl.style.display = 'none';
        this.errorEl.style.display = 'none';
        this.appEl.style.display = 'block';

        this.updateStationDisplay();
        this.renderLineSelector();
        this.renderDirectionSelector();
        this.updateTrainInfo();

        // 设置按钮事件监听器
        this.sortByDistanceBtnEl.onclick = () => this.showStationSelector();
        this.inputStationBtnEl.onclick = () => this.showStationInput();
    }

    updateStationDisplay() {
        this.stationNameEl.textContent = this.nearestStation.name;
        this.distanceEl.textContent = this.nearestStation.distance > 0
            ? window.i18n.t('distanceAway', { distance: (this.nearestStation.distance * 1000).toFixed(0) })
            : window.i18n.t('selectedStation');
    }

    renderLineSelector() {
        this.lineSelectorEl.innerHTML = '';

        this.nearestStation.lines.forEach(line => {
            const btn = document.createElement('button');
            btn.className = `line-btn ${line.lineName === this.selectedLine.lineName ? 'active' : ''}`;

            // Apply different styles for selected vs unselected lines
            if (line.lineColor && line.lineColor !== null) {
                if (line.lineName === this.selectedLine.lineName) {
                    // Selected line: filled with color
                    btn.style.backgroundColor = line.lineColor;
                    btn.style.color = '#ffffff';
                    btn.style.border = `3px solid ${line.lineColor}`;
                } else {
                    // Unselected line: only thick border, no fill
                    btn.style.backgroundColor = 'transparent';
                    btn.style.color = '#ffffff';
                    btn.style.border = `3px solid ${line.lineColor}`;
                }
            }

            // Use formatLineName to get the localized line name for display
            btn.textContent = this.formatLineName(line.route);
            btn.onclick = () => this.selectLine(line);
            this.lineSelectorEl.appendChild(btn);
        });
    }

    renderDirectionSelector() {
        this.directionSelectorEl.innerHTML = '';

        this.selectedLine.directions.forEach(direction => {
            const btn = document.createElement('button');
            btn.className = `direction-btn ${direction.direction === this.selectedDirection.direction ? 'active' : ''}`;
            btn.textContent = window.i18n.t('nextTrainTo', { destination: direction.direction });
            btn.onclick = () => this.selectDirection(direction);
            this.directionSelectorEl.appendChild(btn);
        });
    }

    selectLine(line) {
        this.selectedLine = line;
        this.selectedDirection = line.directions[0];
        this.renderLineSelector();
        this.renderDirectionSelector();
        this.updateTrainInfo();
    }

    selectDirection(direction) {
        this.selectedDirection = direction;
        this.renderDirectionSelector();
        this.updateTrainInfo();
    }

    updateTrainInfo() {
        const nextTrain = this.getNextTrain();
        if (!nextTrain) {
            this.trainTimeEl.textContent = window.i18n.t('trainTimeDefault');
            this.countdownEl.textContent = window.i18n.t('noService');
            this.trainInfoEl.textContent = '';
            return;
        }

        this.trainTimeEl.textContent = nextTrain.time;
        const lineNameTranslated = this.formatLineName(this.selectedLine.route);
        this.trainInfoEl.textContent = `${lineNameTranslated} · ${this.selectedDirection.direction}`;
    }

    getNextTrain() {
        const now = new Date();
        const currentTime = now.getHours() * 60 + now.getMinutes();
        const times = this.selectedDirection.schedule.weekday.times;

        if (!times || times.length === 0) {
            return null;
        }

        // Convert times to minutes and find next train
        const timeInMinutes = times.map(time => this.timeToMinutes(time));
        const nextTime = timeInMinutes.find(time => time > currentTime);

        if (!nextTime) {
            return null;
        }

        return {
            time: this.minutesToTime(nextTime),
            minutes: nextTime
        };
    }

    timeToMinutes(timeStr) {
        const [hours, minutes] = timeStr.split(':').map(Number);
        return hours * 60 + minutes;
    }

    minutesToTime(minutes) {
        const hours = Math.floor(minutes / 60);
        const mins = minutes % 60;
        return `${hours.toString().padStart(2, '0')}:${mins.toString().padStart(2, '0')}`;
    }

    startCountdown() {
        this.updateCountdown();
        this.countdownInterval = setInterval(() => {
            this.updateCountdown();
        }, 1000);
    }

    updateCountdown() {
        const nextTrain = this.getNextTrain();
        if (!nextTrain) {
            this.countdownEl.textContent = window.i18n.t('noService');
            return;
        }

        const now = new Date();
        const currentMinutes = now.getHours() * 60 + now.getMinutes();
        const currentSeconds = now.getSeconds();

        const timeDiff = nextTrain.minutes - currentMinutes;

        if (timeDiff < 0) {
            this.updateTrainInfo();
            return;
        }

        if (timeDiff === 0) {
            const secondsLeft = 60 - currentSeconds;
            if (secondsLeft <= 0) {
                this.updateTrainInfo();
                return;
            }
            this.countdownEl.textContent = window.i18n.t('departsInSeconds', { seconds: secondsLeft });
        } else {
            const totalSeconds = timeDiff * 60 - currentSeconds;
            const minutes = Math.floor(totalSeconds / 60);
            const seconds = String(totalSeconds % 60);
            this.countdownEl.textContent = window.i18n.t('departsIn', { minutes, seconds });
        }
    }

    showError(message) {
        this.loadingEl.style.display = 'none';
        this.appEl.style.display = 'none';
        this.errorEl.style.display = 'block';
        this.errorEl.textContent = message;
    }

    showLocationFallback() {
        this.loadingEl.style.display = 'none';
        this.errorEl.style.display = 'block';
        this.errorEl.innerHTML = `
            <div style="text-align: center;">
                <p style="margin-bottom: 20px;">${window.i18n.t('noLocationFallback')}</p>
                <div style="margin-bottom: 20px;">
                    <input type="text" id="stationInput" placeholder="${window.i18n.t('searchPlaceholder')}" 
                           style="width: 100%; padding: 15px; border: none; border-radius: 10px; 
                                  background: rgba(255,255,255,0.9); color: #333; font-size: 16px;
                                  margin-bottom: 10px;">
                    <div id="searchResults" style="max-height: 200px; overflow-y: auto;"></div>
                </div>
            </div>
        `;

        const input = document.getElementById('stationInput');
        const results = document.getElementById('searchResults');

        input.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            if (!query) {
                results.innerHTML = '';
                return;
            }

            const filtered = this.data.stations.filter(station =>
                station.name.includes(query)
            );

            results.innerHTML = filtered.map(station =>
                `<button onclick="app.selectStationManually('${station.name}')" 
                 style="display: block; width: 100%; margin: 5px 0; padding: 12px; 
                        background: rgba(255,255,255,0.8); border: none; border-radius: 8px; 
                        color: #333; font-size: 15px; cursor: pointer; text-align: left;">
                    ${station.name}
                </button>`
            ).join('');
        });

        input.focus();
    }

    selectStationManually(stationName) {
        this.nearestStation = this.data.stations.find(s => s.name === stationName);
        this.nearestStation.distance = 0; // 手动选择时不显示距离
        this.selectedLine = this.nearestStation.lines[0];
        this.selectedDirection = this.nearestStation.lines[0].directions[0];

        this.setupUI();
        this.startCountdown();
    }

    showStationSelector() {
        // 如果有用户位置，按距离排序；否则按字母顺序排序
        let sortedStations;
        if (this.userLocation) {
            sortedStations = [...this.data.stations].map(station => {
                const distance = this.calculateDistance(
                    this.userLocation.lat,
                    this.userLocation.lng,
                    station.lat,
                    station.lng
                );
                return { ...station, distance };
            }).sort((a, b) => a.distance - b.distance);
        } else {
            sortedStations = [...this.data.stations].sort((a, b) => a.name.localeCompare(b.name));
        }

        this.errorEl.style.display = 'block';
        this.appEl.style.display = 'none';
        this.errorEl.innerHTML = `
            <div style="text-align: center;">
                <p style="margin-bottom: 20px;">${this.userLocation ? window.i18n.t('nearbyStations') : window.i18n.t('allStations')}</p>
                <div id="stationList" style="max-height: 400px; overflow-y: auto;">
                    ${sortedStations.map(station => `
                        <button onclick="app.selectStationFromList('${station.name}')" 
                         style="display: block; width: 100%; margin: 5px 0; padding: 12px; 
                                background: rgba(255,255,255,0.8); border: none; border-radius: 8px; 
                                color: #333; font-size: 15px; cursor: pointer; text-align: left;">
                            ${station.name}
                        </button>
                    `).join('')}
                </div>
                <button onclick="app.backToMain()" 
                 style="margin-top: 15px; padding: 12px 24px; 
                        background: rgba(255,255,255,0.3); border: none; border-radius: 8px; 
                        color: white; font-size: 16px; cursor: pointer;">
                    ${window.i18n.t('back')}
                </button>
            </div>
        `;
    }

    showStationInput() {
        this.errorEl.style.display = 'block';
        this.appEl.style.display = 'none';
        this.errorEl.innerHTML = `
            <div style="text-align: center;">
                <p style="margin-bottom: 20px;">${window.i18n.t('enterStationName')}</p>
                <div style="margin-bottom: 20px;">
                    <input type="text" id="stationInput" placeholder="${window.i18n.t('searchPlaceholder')}" 
                           style="width: 100%; padding: 15px; border: none; border-radius: 10px; 
                                  background: rgba(255,255,255,0.9); color: #333; font-size: 16px;
                                  margin-bottom: 10px;">
                    <div id="searchResults" style="max-height: 300px; overflow-y: auto;"></div>
                </div>
                <button onclick="app.backToMain()" 
                 style="padding: 12px 24px; background: rgba(255,255,255,0.3); 
                        border: none; border-radius: 8px; color: white; font-size: 16px; cursor: pointer;">
                    ${window.i18n.t('back')}
                </button>
            </div>
        `;

        const input = document.getElementById('stationInput');
        const results = document.getElementById('searchResults');

        input.addEventListener('input', (e) => {
            const query = e.target.value.trim();
            if (!query) {
                results.innerHTML = '';
                return;
            }

            const filtered = this.data.stations.filter(station =>
                station.name.includes(query)
            );

            results.innerHTML = filtered.map(station =>
                `<button onclick="app.selectStationFromList('${station.name}')" 
                 style="display: block; width: 100%; margin: 5px 0; padding: 12px; 
                        background: rgba(255,255,255,0.8); border: none; border-radius: 8px; 
                        color: #333; font-size: 15px; cursor: pointer; text-align: left;">
                    ${station.name}
                </button>`
            ).join('');
        });

        input.focus();
    }

    selectStationFromList(stationName) {
        this.nearestStation = this.data.stations.find(s => s.name === stationName);
        // 计算距离（如果有用户位置）
        if (this.userLocation) {
            this.nearestStation.distance = this.calculateDistance(
                this.userLocation.lat,
                this.userLocation.lng,
                this.nearestStation.lat,
                this.nearestStation.lng
            );
        } else {
            this.nearestStation.distance = 0;
        }

        this.selectedLine = this.nearestStation.lines[0];
        this.selectedDirection = this.nearestStation.lines[0].directions[0];

        this.errorEl.style.display = 'none';
        this.appEl.style.display = 'block';

        this.updateStationDisplay();

        this.renderLineSelector();
        this.renderDirectionSelector();
        this.updateTrainInfo();
        this.startCountdown();
    }

    backToMain() {
        this.errorEl.style.display = 'none';
        this.appEl.style.display = 'block';
    }
}

let app;
document.addEventListener('DOMContentLoaded', () => {
    app = new NextTrainApp();
});