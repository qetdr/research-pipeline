"""
Module where final, clean tables are created.
The code must follow the given sequence
"""
import os # accessing directories
import wget # file download
import pandas as pd
# from scripts.crossref_queries import *
from scripts.augmentations import *
from scripts.augmentations import check_or_prepare_journal_metrics

def article_ready():
    # Check if clean 'article' table exists
    if os.path.exists('dags/data_ready/article.csv'):
        article = pd.read_csv('dags/data_ready/article.csv')
        print("Clean table 'article'.")
        return article
    else:
        # Check if augments already done
        if os.path.exists('dags/tables/article_augmented_raw.csv'):
            article = pd.read_csv('dags/tables/article_augmented_raw.csv')
        else:
            # Candidate for citation updating!!
            print("Table 'article' will be augmented...")
            print("This make take several hours...")
            article = pd.read_csv('dags/tables/article.csv')

            # Use Crossref API for extracting cites, paper type, and journal ISSNs
            batches = range(0, len(article), 2000)
            for b in batches:
                start_range = b
                end_range = b + 2000
                # Use the custom augmentation script
                ## NB! 5k records in appx 30min, 2k records in appx 14min 
                fetch_article_augments(start_range, end_range, article)
            # Last batch
            print(time.ctime())
            start_article = time.time()
            start_range = batches[-1]
            end_range = len(article)
            fetch_article_augments(start_range, end_range, article)
            end_article = time.time()
            end_article - start_article/60
            end_batches = time.time()
            print(f'End of article augmentation: {end_batches}')

            # Write to a separate csv (without filtering
            article.to_csv('dags/data_ready/article_augmented_raw.csv', index = False)

        # Include only journal articles
        article_journal = article[article['type'] == 'journal-article'].reset_index(drop = True)

        # Write to 'data_ready' directory
        print("Writing a clean 'article.csv'")
        article_journal.to_csv('dags/data_ready/article.csv', index = False)
        print("Clean table 'article' saved as .csv.")
        return article_journal

# Clean Journal data
def journal_ready():

    if os.path.exists('dags/data_ready/journal.csv'):
        journal = pd.read_csv('dags/data_ready/journal.csv')
        print("Clean table 'journal' exists.")
        return journal
    else:
        print("Preparing table 'journal'...")
        article = pd.read_csv('dags/data_ready/article.csv')
        journal = pd.read_csv('dags/tables/journal.csv')

        # Import the journal database data
        check_or_prepare_journal_metrics() # from augmentations.py

        cwts21 = pd.read_csv('dags/augmentation/cwts2021.csv')
        
        # Find the journals
        journal['journal_issn'] = article['journal_issn'].unique() # NB!! 'article' must be in pwd
        journal = journal[~journal['journal_issn'].isnull()] # remove NAs
        journal = journal.sort_values('journal_issn').reset_index(drop = True)

        print(f'The number of unique journals: {len(journal)}')
        journal = find_journal_stats(journal, cwts21) # from augmentations.py

        print("Writing a clean 'journal.csv'")
        journal.to_csv('dags/data_ready/journal.csv', index = False)
        print("'journal.csv' written to 'data_ready' directory!")
        print("Clean table 'journal' saved as .csv.")
        return journal

# Clean Authorship data
def authorship_ready(article):
    if os.path.exists('dags/data_ready/authorship.csv'):
        authorship = pd.read_csv('dags/data_ready/authorship.csv')
        print("Clean table 'authorship' exists.")
        return authorship
    else:
        print("Preparing table 'authorship'...")
        authorship = pd.read_csv('dags/tables/authorship.csv')
        # Include only the relations in 'article' table
        authorship = authorship[authorship['article_id'].isin(article['article_id'])].sort_values('article_id').reset_index(drop = True)
        # Write to csv
        authorship.to_csv('dags/data_ready/authorship.csv', index = False)
        print("Clean table 'authorship' saved as .csv.")
        return authorship
        
# Clean Author data
def author_ready(article, authorship):
    if os.path.exists('dags/data_ready/author.csv'):
        author = pd.read_csv('dags/data_ready/author.csv')
        print("Clean table 'author' exists.")
        return author
    else:
        author = pd.read_csv('dags/tables/author.csv').drop_duplicates()

        # Filter authors
        author = author[author['author_id'].isin(authorship['author_id'])].drop_duplicates(['author_id']).reset_index(drop = True)

        # Augment gender
        print('Importing gender information...')
        names_genders = pd.read_csv('dags/augmentation/names_genders.csv')[['first_name', 'gender']]
        author = author.merge(names_genders, on = 'first_name', how = 'left')
        print('Gender augmentation done where possible')

        # Number of publications
        npubs = pd.DataFrame(authorship.reset_index(drop = True).groupby('author_id').size()).sort_values('author_id').reset_index()
        npubs.columns = ['author_id', 'total_pubs']
        author = author.merge(npubs, on = 'author_id')

        # Additional augments
        ## Statistics table
        stats = authorship.merge(article[['article_id', 'n_cites', 'n_authors']], on = 'article_id').sort_values('author_id').reset_index(drop = True)

        ## Add new columns to author table
        author['total_cites'] = np.zeros(len(author))
        author['avg_cites'] = np.zeros(len(author))
        author['med_coauthors'] = np.zeros(len(author))
        author['n_unique_coauthors'] = np.zeros(len(author))
        author['hindex'] = np.zeros(len(author))

        ## Add statistics to authors
        ### NB! Slow run...
        print('Computing author statistics...')
        for i in tqdm(range(len(author))):    
            author_id = author.loc[i, 'author_id']
            papers = stats[stats['author_id'] == author_id].sort_values('n_cites').reset_index(drop = True)
            citations = papers['n_cites'].sort_values(ascending = False).reset_index(drop = True)

            # The nyumber of unique co-authors
            articles = authorship[authorship['author_id'] == author_id]['article_id']
            author.loc[i, 'n_unique_coauthors'] = authorship[authorship['article_id'].isin(articles)]['author_id'].unique().size - 1

                # Stats
            author.loc[i, 'total_cites'] = papers['n_cites'].sum() # Total number of citations
            author.loc[i, 'avg_cites'] = round(author.loc[i, 'total_cites']/len(papers),3) # Average number of citations per paper
            author.loc[i, 'med_coauthors'] = np.median(papers['n_authors']-1) # subtract oneself

                # h-index
            author.loc[i, 'hindex'] = hindex(citations, len(citations))

        # Compute stats-based ranks
        author['rank_total_pubs'] = author['total_pubs'].rank(ascending = 0).values.astype(int)
        author['rank_total_cites'] = author['total_cites'].rank(ascending = 0).values.astype(int)
        author['rank_avg_cites'] = author['avg_cites'].rank(ascending = 0).values.astype(int)
        author['rank_hindex'] = author['hindex'].rank(ascending = 0).values.astype(int)
        author = author.sort_values('rank_hindex').reset_index(drop = True) # sort by h-index

        # Format data types
        author['total_cites'] = author['total_cites'].astype(int)
        author['n_unique_coauthors'] = author['n_unique_coauthors'].astype(int)
        author['hindex'] = author['hindex'].astype(int)

        print('Computing done!') 
        print('Saving author table to .csv...') 
        # Save to csv
        author.to_csv('dags/data_ready/author.csv', index = False)
        print("Clean table 'author' saved as .csv.")
        return author

# Clean Article_category data
def article_category_ready(article):
    if os.path.exists('dags/data_ready/article_category.csv'):
        article_category = pd.read_csv('dags/data_ready/article_category.csv')
        print("Clean table 'article_category' exists.")
        return article_category
    else:
        article_category = pd.read_csv('dags/tables/article_category.csv')
        article_category = article_category[article_category['article_id'].isin(article['article_id'])].reset_index(drop = True)
        article_category.to_csv('dags/data_ready/article_category.csv', index = False)
        print("Clean table 'article_category' saved as .csv.")
        return article_category

# Clean Category data 
def category_ready(article_category):
    if os.path.exists('dags/data_ready/category.csv'):
        category = pd.read_csv('dags/data_ready/category.csv')
        print("Clean table 'category' exists.")
        return article_category
    else:
        category = pd.read_csv('dags/tables/category.csv')
        category = category[category['category_id'].isin(article_category['category_id'])].reset_index(drop = True)
        category.to_csv('dags/data_ready/category.csv', index = False)
        print("Clean table 'category' saved as .csv.")
        return article_category
