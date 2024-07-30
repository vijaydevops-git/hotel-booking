from flask import Flask, render_template, request

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/search', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        location = request.form['location']
        check_in = request.form['check_in']
        check_out = request.form['check_out']
        return f'Search results for {location} from {check_in} to {check_out}'
    return render_template('search.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0')
